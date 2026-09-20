import Combine
import Foundation

/// Where a `sandy://` link wants to go.
enum DeepLink: Equatable {
    case call, chat, quickAdd
}

/// Routes `sandy://` URLs from the widgets, the Live Activity and Control Center.
///
/// • sandy://call      — open the live voice call
/// • sandy://call/end  — end the running call
/// • sandy://chat      — the Sandy (chat) tab
/// • sandy://quickadd  — the quick-add window
///
/// A link that arrives before the main screen exists (cold launch, sign-in) waits
/// in `pending` until `MainTabView` appears and consumes it.
@MainActor
final class DeepLinkRouter: ObservableObject {
    static let shared = DeepLinkRouter()

    @Published var pending: DeepLink?

    /// Fires when a link asks to end the running call; `LiveVoiceView` listens.
    let endCall = PassthroughSubject<Void, Never>()

    /// Returns false for URLs that are not ours (e.g. Google sign-in).
    @discardableResult
    func handle(_ url: URL) -> Bool {
        guard url.scheme?.lowercased() == "sandy" else { return false }
        let host = (url.host ?? "").lowercased()
        let path = url.path.lowercased()
        switch host {
        case "call":
            if path == "/end" {
                endCall.send()
                CallLiveActivity.shared.end()
            } else if !CallLiveActivity.shared.isCallRunning {
                pending = .call
            }
        case "chat":
            pending = .chat
        case "quickadd":
            pending = .quickAdd
        default:
            break
        }
        return true
    }

    /// Picks up a link left in the App Group by the Control Center intent
    /// (only if recent — a stale one must not start a call days later).
    func consumeSharedPending() {
        let store = UserDefaults(suiteName: SandyLinks.appGroup)
        guard let raw = store?.string(forKey: SandyLinks.pendingKey) else { return }
        let at = store?.double(forKey: SandyLinks.pendingAtKey) ?? 0
        store?.removeObject(forKey: SandyLinks.pendingKey)
        store?.removeObject(forKey: SandyLinks.pendingAtKey)
        guard Date().timeIntervalSince1970 - at < 60, let url = URL(string: raw) else { return }
        handle(url)
    }
}
