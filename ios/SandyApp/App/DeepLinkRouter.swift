import Combine
import Foundation

enum DeepLink: Equatable {
    case call, chat, quickAdd, scheduledTasks
    /// A page to sign in to by hand (`sandy://browser/login?url=…`).
    case browserLogin(URL)
    /// «Sandy's browser» for a fill (`sandy://browser/live?job=…`).
    case browserLive(String)
}

/// Routes sandy://call, call/end, chat, quickadd, focus/stop, tasks (a task's email:
/// «افتح المهمة» opens the Tasks screen), browser/login?url= and browser/live?job= (links in
/// Sandy's replies).
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
        case "tasks":
            ask(.scheduledTasks)
        case "browser":
            let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            let value = { (name: String) in query.first { $0.name == name }?.value }
            if path == "/login", let raw = value("url"), let page = URL(string: raw),
               ["http", "https"].contains(page.scheme?.lowercased() ?? "") {
                ask(.browserLogin(page))
            } else if path == "/live", let job = value("job"), !job.isEmpty {
                ask(.browserLive(job))
            }
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
