import SwiftUI

/// The one «… · تراجع» offer on screen, for anything just ticked done or deleted.
///
/// A delete leaves the screen at once but reaches the server only when its offer ends
/// (four seconds, the next offer, or the app leaving the front), so «تراجع» puts it
/// back with nothing to recreate.
@MainActor
final class UndoCenter: ObservableObject {
    static let shared = UndoCenter()

    struct Offer: Identifiable {
        let id = UUID()
        let message: String
        let icon: String
        let undo: () -> Void
        /// What happens if nobody undoes it (the server delete); nothing for a done tick.
        let commit: @MainActor () async -> Void
    }

    @Published private(set) var offer: Offer?

    func offer(_ message: String, icon: String, undo: @escaping () -> Void,
               commit: @escaping @MainActor () async -> Void = {}) {
        commitNow()
        offer = Offer(message: message, icon: icon, undo: undo, commit: commit)
        Announce.say(message)
    }

    func undo() {
        guard let current = offer else { return }
        offer = nil
        current.undo()
    }

    /// Ends the offer as kept: a pending delete goes to the server.
    func commitNow() {
        guard let current = offer else { return }
        offer = nil
        Task { await current.commit() }
    }

    /// Before a sign-out: the offer is kept and sent now, while the session's token is
    /// still in place, waiting at most `limit`, so no network never holds the sign-out up
    /// (a block delete is in the outbox by then and waits there for this account).
    func commitBeforeSignOut(limit: Duration = .seconds(3)) async {
        guard let current = offer else { return }
        offer = nil
        await withTaskGroup(of: Void.self) { group in
            group.addTask { await current.commit() }
            group.addTask { try? await Task.sleep(for: limit) }
            await group.next()
            group.cancelAll()
        }
    }

    /// The session ended: an offer still up is dropped, never sent as the next account.
    func drop() {
        offer = nil
    }

    /// The timer ran out on this offer (a newer one may have replaced it).
    fileprivate func expire(_ id: UUID) {
        if offer?.id == id { commitNow() }
    }
}

/// The offer as a glass bar with its «تراجع» button.
private struct UndoToast: View {
    @EnvironmentObject var lang: LanguageManager
    let offer: UndoCenter.Offer

    var body: some View {
        HStack(spacing: Theme.Spacing.md) {
            Image(systemName: offer.icon).foregroundColor(Theme.Colors.success)
            Text(offer.message)
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.primaryText)
                .lineLimit(1)
            Spacer(minLength: 0)
            Button(lang.s("blocks.undo")) { withAnimation { UndoCenter.shared.undo() } }
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.accent)
        }
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.vertical, 12)
        .liquidGlass(cornerRadius: 18)
        .padding(.horizontal, Theme.Spacing.md)
        .transition(.move(edge: .bottom).combined(with: .opacity))
        .task(id: offer.id) {
            try? await Task.sleep(for: .seconds(4))
            withAnimation { UndoCenter.shared.expire(offer.id) }
        }
    }
}

private struct UndoOverlay: ViewModifier {
    @ObservedObject private var center = UndoCenter.shared
    let bottom: CGFloat

    func body(content: Content) -> some View {
        content
            .overlay(alignment: .bottom) {
                if let offer = center.offer {
                    UndoToast(offer: offer).padding(.bottom, bottom)
                }
            }
            .animation(Animation.spring(response: 0.4, dampingFraction: 0.85).reduced, value: center.offer?.id)
    }
}

extension View {
    /// Shows the current undo offer at the bottom.
    func undoOverlay(bottom: CGFloat = 0) -> some View {
        modifier(UndoOverlay(bottom: bottom))
    }
}
