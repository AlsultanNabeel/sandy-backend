//
//  SandyFocusAttributes.swift — shared between the app and the widget extension.
//
//  KEEP IDENTICAL: this file exists twice, byte for byte —
//    ios/SandyApp/Widgets/SandyFocusAttributes.swift   (app target)
//    ios/SandyWidget/SandyFocusAttributes.swift        (widget target)
//  ActivityKit matches a Live Activity to its UI by the attributes type, so both
//  targets must compile the same definition. Edit one, copy it over the other.
//

import ActivityKit
import Foundation

/// The `sandy://focus/...` links the focus Live Activity opens.
enum SandyFocusLinks {
    /// Finishes the running focus session (handled by `DeepLinkRouter`).
    static let stop = URL(string: "sandy://focus/stop")!
}

/// A focus (pomodoro) session on the Lock Screen and in the Dynamic Island.
///
/// The countdown is drawn by the system from `phaseStartedAt...phaseEndsAt`
/// (`Text(timerInterval:countsDown:)`), so it keeps ticking while the app sleeps;
/// the app only updates the state when the phase or cycle changes.
struct SandyFocusAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        /// Start of the current phase — the lower bound of the countdown range.
        var phaseStartedAt: Date
        /// When the current phase (focus or break) ends.
        var phaseEndsAt: Date
        var isBreak: Bool
        /// 1-based cycle index and total cycles.
        var cycle: Int
        var cycles: Int
    }

    /// What the user is focusing on (may be empty).
    var label: String
    /// App language at session start: Arabic text + right-to-left, or English.
    var isArabic: Bool
}
