//
//  SandyCallAttributes.swift — shared between the app and the widget extension.
//
//  KEEP IDENTICAL: this file exists twice, byte for byte —
//    ios/SandyApp/Widgets/SandyCallAttributes.swift   (app target)
//    ios/SandyWidget/SandyCallAttributes.swift        (widget target)
//  ActivityKit matches a Live Activity to its UI by the attributes type, and the
//  Control Center intent must be a member of both targets. Edit one, copy it
//  over the other.
//

import ActivityKit
import AppIntents
import Foundation

// MARK: - Deep links

/// The `sandy://` URLs the widgets, Live Activity and Control Center open.
enum SandyLinks {
    static let appGroup = "group.com.sandy.app"
    /// Written by `TalkToSandyIntent`, read (once) by the app when it becomes active.
    static let pendingKey = "pending_link"
    static let pendingAtKey = "pending_link_at"

    static let call = URL(string: "sandy://call")!
    static let endCall = URL(string: "sandy://call/end")!
    static let chat = URL(string: "sandy://chat")!
    static let quickAdd = URL(string: "sandy://quickadd")!
}

// MARK: - Live voice call (Live Activity + Dynamic Island)

struct SandyCallAttributes: ActivityAttributes {
    enum Phase: String, Codable, Hashable {
        case connecting, listening, speaking
    }

    struct ContentState: Codable, Hashable {
        var phase: Phase
        /// When the call started — drives the running call timer.
        var startedAt: Date
    }

    /// App language at call start: Arabic text + right-to-left, or English.
    var isArabic: Bool
}

// MARK: - Control Center: Talk to Sandy

/// Opens Sandy straight into a live voice call. Runs in the app (openAppWhenRun),
/// which opens `sandy://call`; the App Group flag is a fallback the app picks up
/// when it becomes active, in case the URL itself is not delivered.
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
