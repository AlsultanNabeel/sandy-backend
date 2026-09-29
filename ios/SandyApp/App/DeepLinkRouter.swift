import Combine
import Foundation

enum DeepLink: Equatable {
    case call, chat, quickAdd
}

/// Routes sandy://call, call/end, chat, quickadd, focus/stop.
/// A link arriving before the main screen exists waits in `pending` for `MainTabView`.
@MainActor
final class DeepLinkRouter: ObservableObject {
    static let shared = DeepLinkRouter()

    @Published var pending: DeepLink?

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
        case "focus":
            if path == "/stop" { FocusLiveActivity.shared.stopFromLink() }
        default:
            break
        }
        return true
    }

    /// Link left by the Control Center intent; ignored if stale so it can't start a call days later.
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
