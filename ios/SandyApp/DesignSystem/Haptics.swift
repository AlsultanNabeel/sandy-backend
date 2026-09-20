import UIKit

/// One place for the app's haptics, so the same moment always feels the same.
///
/// Light and rare on purpose: a tap you feel on every scroll stops meaning
/// anything. Each case names a *moment*, not a vibration strength, so a call
/// site reads as intent (`Haptics.play(.listening)`) and the feel can be tuned
/// here once.
enum Haptics {
    enum Moment {
        /// Sandy starts listening (call connected, or her turn ended).
        case listening
        /// Sandy starts speaking.
        case speaking
        /// A message was sent.
        case send
        /// Something was saved or completed (task done, reminder set).
        case success
        /// Something failed and the user should look.
        case failure
        /// A selection changed (tab, toggle, picker).
        case selection
        /// A card was picked up or dropped.
        case drag
    }

    /// Safe from any context: the feedback generators are main-actor types, so
    /// a call off the main thread is hopped over rather than refused.
    static func play(_ moment: Moment) {
        if Thread.isMainThread {
            MainActor.assumeIsolated { fire(moment) }
        } else {
            DispatchQueue.main.async { fire(moment) }
        }
    }

    @MainActor
    private static func fire(_ moment: Moment) {
        switch moment {
        case .listening: impact(.soft, 0.7)
        case .speaking:  impact(.light, 0.5)
        case .send:      impact(.light, 0.6)
        case .drag:      impact(.light, 1.0)
        case .selection: UISelectionFeedbackGenerator().selectionChanged()
        case .success:   UINotificationFeedbackGenerator().notificationOccurred(.success)
        case .failure:   UINotificationFeedbackGenerator().notificationOccurred(.error)
        }
    }

    @MainActor
    private static func impact(_ style: UIImpactFeedbackGenerator.FeedbackStyle,
                               _ intensity: CGFloat) {
        UIImpactFeedbackGenerator(style: style).impactOccurred(intensity: intensity)
    }
}
