import SwiftUI
import TipKit

// The quiet ways the app teaches itself and asks for a rating: a few one-time tips for
// what is hidden behind a gesture (TipKit keeps them shown once, never again, at most one
// a day), and a rating request only after a good moment.

// MARK: - One-time tips

/// «Hold Sandy to call her» — on the orb, the first time only.
struct OrbCallTip: Tip {
    var title: Text { Text(translate(AppLocale.lang, "tips.orbTitle")) }
    var message: Text? { Text(translate(AppLocale.lang, "tips.orbBody")) }
    var image: Image? { Image(systemName: "phone.fill") }
}

/// Rows hide their actions: tap to edit, hold for snooze, done and delete.
struct RowActionsTip: Tip {
    var title: Text { Text(translate(AppLocale.lang, "tips.rowsTitle")) }
    var message: Text? { Text(translate(AppLocale.lang, "tips.rowsBody")) }
    var image: Image? { Image(systemName: "hand.tap") }
    var actions: [Action] { [Action(id: "ok", title: translate(AppLocale.lang, "tips.gotIt"))] }
}

/// The month strip opens a single day.
struct LifeDayTip: Tip {
    var title: Text { Text(translate(AppLocale.lang, "tips.dayTitle")) }
    var message: Text? { Text(translate(AppLocale.lang, "tips.dayBody")) }
    var image: Image? { Image(systemName: "calendar") }
    var actions: [Action] { [Action(id: "ok", title: translate(AppLocale.lang, "tips.gotIt"))] }
}

/// A message held down: copy, share, write again, edit.
struct MessageActionsTip: Tip {
    var title: Text { Text(translate(AppLocale.lang, "tips.messageTitle")) }
    var message: Text? { Text(translate(AppLocale.lang, "tips.messageBody")) }
    var image: Image? { Image(systemName: "text.bubble") }
    var actions: [Action] { [Action(id: "ok", title: translate(AppLocale.lang, "tips.gotIt"))] }
}

/// An inline tip in the app's style that goes for good on «فهمت» or its ✕.
struct OneTimeTip<T: Tip>: View {
    let tip: T

    var body: some View {
        TipView(tip) { _ in tip.invalidate(reason: .actionPerformed) }
            .tipBackground(Theme.Colors.surface.opacity(0.6))
            .tint(Theme.Colors.accent)
    }
}

enum Guidance {
    /// Once at launch: tips show at most one a day, and each only until it is dismissed.
    static func configure() {
        try? Tips.configure([.displayFrequency(.daily), .datastoreLocation(.applicationDefault)])
    }
}

// MARK: - Asking for a rating

/// Asks for an App Store rating only after something went well — tasks being finished,
/// or a week of use with several conversations — never right after an error, and at most
/// once every four months (Apple adds its own limit on top).
@MainActor
final class ReviewPrompter: ObservableObject {
    static let shared = ReviewPrompter()

    /// Set when now is a good moment; the main screen asks and clears it.
    @Published var askNow = false

    private let defaults = UserDefaults.standard
    private static let gap: TimeInterval = 120 * 86_400
    private static let calmAfterError: TimeInterval = 10 * 60

    private init() {
        if defaults.object(forKey: "review.firstUse") == nil {
            defaults.set(Date(), forKey: "review.firstUse")
        }
    }

    /// A task ticked done: every fifth one is a good moment.
    func noteTaskDone() {
        let done = defaults.integer(forKey: "review.tasksDone") + 1
        defaults.set(done, forKey: "review.tasksDone")
        if done % 5 == 0 { consider() }
    }

    /// A reply arrived: after a week of use and ten replies, that is a good moment.
    func noteReply() {
        let replies = defaults.integer(forKey: "review.replies") + 1
        defaults.set(replies, forKey: "review.replies")
        let first = defaults.object(forKey: "review.firstUse") as? Date ?? Date()
        if replies >= 10, Date().timeIntervalSince(first) >= 7 * 86_400 { consider() }
    }

    /// Something failed: no asking for a while.
    func noteError() {
        defaults.set(Date(), forKey: "review.lastError")
    }

    private func consider() {
        let now = Date()
        if let error = defaults.object(forKey: "review.lastError") as? Date,
           now.timeIntervalSince(error) < Self.calmAfterError { return }
        if let asked = defaults.object(forKey: "review.lastAsked") as? Date,
           now.timeIntervalSince(asked) < Self.gap { return }
        defaults.set(now, forKey: "review.lastAsked")
        askNow = true
    }
}
