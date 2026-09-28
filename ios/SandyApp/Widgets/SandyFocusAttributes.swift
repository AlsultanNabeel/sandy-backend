// KEEP IDENTICAL: copied in SandyApp/Widgets/ and SandyWidget/. ActivityKit matches by
// attributes type, so both targets must compile the same definition.

import ActivityKit
import Foundation

enum SandyFocusLinks {
    /// Handled by `DeepLinkRouter`.
    static let stop = URL(string: "sandy://focus/stop")!
}

/// The system draws the countdown from `phaseStartedAt...phaseEndsAt`, so it ticks while
/// the app sleeps; the app updates only on phase or cycle change.
struct SandyFocusAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var phaseStartedAt: Date
        var phaseEndsAt: Date
        var isBreak: Bool
        /// 1-based.
        var cycle: Int
        var cycles: Int
    }

    var label: String
    /// App language at session start (Arabic + RTL, or English).
    var isArabic: Bool
}
