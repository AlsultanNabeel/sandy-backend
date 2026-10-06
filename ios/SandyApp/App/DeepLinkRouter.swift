import Combine
import Foundation

enum DeepLink: Equatable {
    case call, chat, quickAdd
}

/// Routes sandy://call, call/end, chat, quickadd, focus/stop.
/// A link arriving before the main screen exists waits in `pending` for `MainTabView`, a
/// minute at most and never across a sign-out: a «talk to Sandy» tapped signed out must not
/// open the mic minutes later, once sign-in is done.
@MainActor
final class DeepLinkRouter: ObservableObject {
    static let shared = DeepLinkRouter()

    @Published private(set) var pending: DeepLink?
    private var pendingAt = Date.distantPast
    static let pendingLife: TimeInterval = 60

    func ask(_ link: DeepLink) {
        pendingAt = Date()
        pending = link
    }

    /// The waiting link, once; nil when there is none or it waited too long.
    func take(now: Date = Date()) -> DeepLink? {
        defer { pending = nil }
        guard let link = pending, now.timeIntervalSince(pendingAt) < Self.pendingLife else { return nil }
        return link
    }

    /// Signed out: a waiting link goes with the session.
    func drop() {
        pending = nil
    }

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
                ask(.call)
            }
        case "chat":
            ask(.chat)
        case "quickadd":
            ask(.quickAdd)
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
