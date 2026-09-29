import UIKit

/// App haptics by moment, not strength; light and rare on purpose.
enum Haptics {
    enum Moment {
        case listening
        case speaking
        case send
        case success
        case failure
        case selection
        case drag
    }

    /// Safe from any thread: hops to the main actor.
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
