import SwiftUI

/// A row the screen reader reads as one thing: what it is, its state, what a double tap
/// does, and the rest of its gestures (tick, snooze, delete) as named actions, since swipes
/// and long presses are hidden from it.
struct RowAccessibility: ViewModifier {
    let label: String
    var value: String = ""
    let hint: String
    let open: () -> Void
    var actions: [(name: String, run: () -> Void)] = []

    func body(content: Content) -> some View {
        actions.reduce(AnyView(
            content
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(label)
                .accessibilityValue(value)
                .accessibilityHint(hint)
                .accessibilityAddTraits(.isButton)
                .accessibilityAction(.default, open)
        )) { view, action in
            AnyView(view.accessibilityAction(named: action.name, action.run))
        }
    }
}

extension View {
    func rowAccessibility(label: String, value: String = "", hint: String, open: @escaping () -> Void,
                          actions: [(name: String, run: () -> Void)] = []) -> some View {
        modifier(RowAccessibility(label: label, value: value, hint: hint, open: open, actions: actions))
    }
}

/// Says something out loud to the screen reader (a reply arrived, an error, an undo).
enum Announce {
    static func say(_ text: String) {
        guard UIAccessibility.isVoiceOverRunning, !text.isEmpty else { return }
        AccessibilityNotification.Announcement(text).post()
    }
}
