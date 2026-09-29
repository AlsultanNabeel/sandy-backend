// KEEP IDENTICAL: copied in SandyApp/Widgets/ and SandyWidget/. ActivityKit matches by
// attributes type, and the Control Center intent must be in both targets.

import ActivityKit
import AppIntents
import Foundation

// MARK: - Deep links

enum SandyLinks {
    static let appGroup = "group.com.sandy.app"
    /// Written by `TalkToSandyIntent`, read once by the app when it becomes active.
    static let pendingKey = "pending_link"
    static let pendingAtKey = "pending_link_at"

    static let call = URL(string: "sandy://call")!
    static let endCall = URL(string: "sandy://call/end")!
    static let chat = URL(string: "sandy://chat")!
    static let quickAdd = URL(string: "sandy://quickadd")!
}

// MARK: - Live voice call

struct SandyCallAttributes: ActivityAttributes {
    enum Phase: String, Codable, Hashable {
        case connecting, listening, speaking
    }

    struct ContentState: Codable, Hashable {
        var phase: Phase
        /// Drives the running call timer.
        var startedAt: Date
    }

    /// App language at call start (Arabic + RTL, or English).
    var isArabic: Bool
}

// MARK: - Control Center: Talk to Sandy

/// Opens `sandy://call`; the App Group flag is a fallback in case the URL isn't delivered.
struct TalkToSandyIntent: AppIntent {
    static let title: LocalizedStringResource = "Talk to Sandy"
    static let description = IntentDescription("Opens Sandy in a live voice call.")
    static let openAppWhenRun: Bool = true

    func perform() async throws -> some IntentResult & OpensIntent {
        let store = UserDefaults(suiteName: SandyLinks.appGroup)
        store?.set(SandyLinks.call.absoluteString, forKey: SandyLinks.pendingKey)
        store?.set(Date().timeIntervalSince1970, forKey: SandyLinks.pendingAtKey)
        return .result(opensIntent: OpenURLIntent(SandyLinks.call))
    }
}
