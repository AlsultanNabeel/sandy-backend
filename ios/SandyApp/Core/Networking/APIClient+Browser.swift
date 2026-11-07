import Foundation

// The browser (`api/browser_api.py`, behind the `browser` switch): the sites Sandy may open,
// his level and sign-in on each, «Sandy's browser» for a fill, and the emergency stop.

/// One site: what Sandy may do there («read», «fill», «submit») and whether his sign-in is kept.
struct BrowserSite: Decodable, Identifiable, Hashable {
    let site: String
    var level: String
    var signedIn: Bool
    let sessionAt: String?

    var id: String { site }

    static let read = "read", fill = "fill", submit = "submit"
    static let levels = [read, fill, submit]

    /// The site a name or a link he types belongs to: its host, lowercase, without «www.»
    /// (the server reads it the same way, `browser_sites.site_of`).
    static func name(of typed: String) -> String {
        let raw = typed.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let host = URLComponents(string: raw.contains("://") ? raw : "https://" + raw)?.host ?? raw
        return host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }

    enum CodingKeys: String, CodingKey {
        case site, level
        case signedIn = "signed_in", sessionAt = "session_at"
    }
}

/// A fill still open: running, waiting for his yes, or his to finish.
struct BrowserJob: Decodable, Identifiable, Hashable {
    let id: String
    let site: String
    let status: String
}

/// Steel's view of a fill: to watch, or (`control`) to drive.
struct BrowserLive: Decodable, Equatable {
    let url: String
    let control: Bool
}

/// What the phone hands the server after he signs in by hand: that site's cookies and its
/// storage, never a password.
struct BrowserSignIn: Encodable {
    struct Cookie: Encodable {
        let name: String
        let value: String
        let domain: String
        let path: String
        let secure: Bool
        let httpOnly: Bool
        let expires: Double?
        let sameSite: String?
    }
    let cookies: [Cookie]
    let storage: [String: [String: String]]
}

private struct BrowserSitesResponse: Decodable { let sites: [BrowserSite] }
private struct BrowserSiteResponse: Decodable { let site: BrowserSite }
private struct BrowserJobsResponse: Decodable { let jobs: [BrowserJob] }
private struct BrowserLevelBody: Encodable { let level: String }
private struct StopState: Decodable { let stopped: Bool }

extension APIClient {
    func browserSites() async throws -> [BrowserSite] {
        let r: BrowserSitesResponse = try await fetch("/api/browser/sites")
        return r.sites
    }

    func setBrowserLevel(site: String, level: String) async throws -> BrowserSite {
        let r: BrowserSiteResponse = try await fetch("/api/browser/sites/\(URLEscape.segment(site))",
                                                     method: "PATCH", body: BrowserLevelBody(level: level))
        return r.site
    }

    func saveBrowserSignIn(site: String, signIn: BrowserSignIn) async throws -> BrowserSite {
        let r: BrowserSiteResponse = try await fetch("/api/browser/sites/\(URLEscape.segment(site))/session",
                                                     method: "POST", body: signIn)
        return r.site
    }

    /// «طلّعها»: his sign-in forgotten; the level stays.
    func signOutBrowserSite(site: String) async throws -> BrowserSite {
        let r: BrowserSiteResponse = try await fetch("/api/browser/sites/\(URLEscape.segment(site))/session",
                                                     method: "DELETE")
        return r.site
    }

    func browserJobs() async throws -> [BrowserJob] {
        let r: BrowserJobsResponse = try await fetch("/api/browser/jobs")
        return r.jobs
    }

    func browserLive(job: String) async throws -> BrowserLive {
        try await fetch("/api/browser/jobs/\(URLEscape.segment(job))/live")
    }

    /// «خليني أكمّل أنا»: Sandy stops and the view is his to drive.
    func takeOverBrowserJob(job: String) async throws -> BrowserLive {
        try await fetch("/api/browser/jobs/\(URLEscape.segment(job))/takeover", method: "POST")
    }

    /// «رجّع التحكم لساندي»: the page he took over is hers again, and she goes on from where it is.
    func giveBackBrowserJob(job: String) async throws {
        try await send("/api/browser/jobs/\(URLEscape.segment(job))/giveback", method: "POST")
    }

    func stopState() async throws -> Bool {
        let r: StopState = try await fetch("/api/stop")
        return r.stopped
    }

    /// The emergency stop (true) or everything back on (false); the state the server keeps.
    func setStopped(_ stopped: Bool) async throws -> Bool {
        let r: StopState = try await fetch("/api/stop", method: stopped ? "POST" : "DELETE")
        return r.stopped
    }
}
