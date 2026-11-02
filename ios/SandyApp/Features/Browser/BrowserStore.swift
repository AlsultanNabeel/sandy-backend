import Foundation

/// The browser's screens show only for an account with `browser` in `/api/features`' `on`.
enum BrowserAccess {
    static let flag = "browser"

    static func shows(on: Set<String>) -> Bool { on.contains(flag) }
}

/// The sites Sandy may open, his open fills and the emergency stop (`APIClient+Browser`).
@MainActor
final class BrowserStore: LoadableStore {
    @Published var sites: [BrowserSite] = []
    @Published var jobs: [BrowserJob] = []
    @Published var stopped = false

    func load(api: APIClient) async {
        let gen = beginLoad()
        defer { endLoad(gen) }
        clearNotice()
        do {
            async let s = api.browserSites()
            async let j = api.browserJobs()
            async let st = api.stopState()
            let (rows, open, now) = try await (s, j, st)
            guard isCurrentLoad(gen) else { return }
            sites = rows
            jobs = open
            stopped = now
        } catch {
            if !error.isCancellation, isCurrentLoad(gen) { notify("browser.loadFailed") }
        }
    }

    /// Shown at once; put back when the server did not take it.
    func setLevel(_ level: String, site: String, api: APIClient) async {
        guard let i = sites.firstIndex(where: { $0.site == site }) else { return }
        let before = sites[i].level
        sites[i].level = level
        do {
            let saved = try await api.setBrowserLevel(site: site, level: level)
            if let j = sites.firstIndex(where: { $0.site == site }) { sites[j] = saved }
        } catch {
            if let j = sites.firstIndex(where: { $0.site == site }) { sites[j].level = before }
            if !error.isCancellation { notify("browser.saveFailed") }
        }
    }

    /// «طلّعها».
    func signOut(site: String, api: APIClient) async {
        do {
            let saved = try await api.signOutBrowserSite(site: site)
            if let i = sites.firstIndex(where: { $0.site == site }) { sites[i] = saved }
        } catch {
            if !error.isCancellation { notify("browser.saveFailed") }
        }
    }

    /// The emergency stop, or everything back on, in one tap.
    func setStopped(_ value: Bool, api: APIClient) async {
        let before = stopped
        stopped = value
        do {
            stopped = try await api.setStopped(value)
            if value { jobs = [] }
        } catch {
            stopped = before
            if !error.isCancellation { notify("browser.saveFailed") }
        }
    }
}
