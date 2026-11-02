import SwiftUI
import WebKit

/// A web page in the app, on a store of its own that lives only as long as the screen: what he
/// does there never mixes with another site or another account.
struct BrowserWebView: UIViewRepresentable {
    let url: URL
    let store: WKWebsiteDataStore
    var onLoad: ((WKWebView) -> Void)?

    func makeCoordinator() -> Coordinator { Coordinator(onLoad: onLoad) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = store
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        context.coordinator.view = view
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        if view.url == nil || context.coordinator.loaded != url {
            context.coordinator.loaded = url
            view.load(URLRequest(url: url))
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        weak var view: WKWebView?
        var loaded: URL?
        let onLoad: ((WKWebView) -> Void)?

        init(onLoad: ((WKWebView) -> Void)?) { self.onLoad = onLoad }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            onLoad?(webView)
        }
    }
}

/// He signs in to a site by hand, here on his phone; Sandy never sees the password. «Done»
/// sends the server that site's cookies and its storage only (`APIClient.saveBrowserSignIn`),
/// and the screen's own store goes with it.
struct BrowserLoginView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let url: URL
    @State private var store = WKWebsiteDataStore.nonPersistent()
    @State private var web: WKWebView?
    @State private var sending = false
    @State private var failed = false

    private var site: String {
        let host = url.host?.lowercased() ?? ""
        return host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Text(lang.s("browser.loginNote"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .padding(Theme.Spacing.sm)
                if failed {
                    SandyNotice(lang.s("browser.loginFailed"), kind: .gentleWarning)
                }
                BrowserWebView(url: url, store: store) { web = $0 }
            }
            .navigationTitle(site)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("common.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.s("browser.loginDone")) { Task { await send() } }.disabled(sending)
                }
            }
        }
    }

    private func belongs(_ domain: String) -> Bool {
        let d = domain.hasPrefix(".") ? String(domain.dropFirst()) : domain.lowercased()
        return d.contains(".") && (d == site || d.hasSuffix("." + site) || site.hasSuffix("." + d))
    }

    private func send() async {
        sending = true
        defer { sending = false }
        let all = await store.httpCookieStore.allCookies()
        let cookies = all.filter { belongs($0.domain) }.map { c in
            BrowserSignIn.Cookie(name: c.name, value: c.value, domain: c.domain, path: c.path, secure: c.isSecure,
                                 httpOnly: c.isHTTPOnly, expires: c.expiresDate?.timeIntervalSince1970,
                                 sameSite: c.sameSitePolicy?.rawValue)
        }
        var storage: [String: [String: String]] = [:]
        if let web, let origin = web.url.flatMap({ u -> String? in
            guard let scheme = u.scheme, let host = u.host else { return nil }
            return "\(scheme)://\(host)"
        }), belongs(web.url?.host ?? "") {
            let raw = try? await web.evaluateJavaScript("JSON.stringify(Object.assign({}, localStorage))") as? String
            if let data = raw?.data(using: .utf8),
               let items = try? JSONDecoder().decode([String: String].self, from: data) {
                // A key named like a password never leaves the phone (the server drops one too).
                storage[origin] = items.filter { key, _ in
                    key.range(of: #"pass(word|code|wd)?|pwd"#, options: [.regularExpression, .caseInsensitive]) == nil
                }
            }
        }
        do {
            _ = try await state.api.saveBrowserSignIn(site: site, signIn: BrowserSignIn(cookies: cookies, storage: storage))
            await store.removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), modifiedSince: .distantPast)
            dismiss()
        } catch {
            failed = true
        }
    }
}

/// «Sandy's browser»: Steel's view of a fill, to watch; «Let me take it from here» stops Sandy
/// and the view is his to drive.
struct LiveBrowserView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    let jobId: String
    @State private var live: BrowserLive?
    @State private var gone = false
    @State private var store = WKWebsiteDataStore.nonPersistent()

    var body: some View {
        VStack(spacing: 0) {
            if let live, let url = URL(string: live.url) {
                BrowserWebView(url: url, store: store)
                    .allowsHitTesting(live.control)
                if !live.control {
                    Button {
                        Task { await takeOver() }
                    } label: {
                        Label(lang.s("browser.takeOver"), systemImage: "hand.raised.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .padding(Theme.Spacing.md)
                }
            } else if gone {
                Text(lang.s("browser.liveGone"))
                    .foregroundColor(Theme.Colors.secondaryText)
                    .padding(Theme.Spacing.lg)
                Spacer()
            } else {
                ProgressView().frame(maxHeight: .infinity)
            }
        }
        .navigationTitle(lang.s("browser.live"))
        .navigationBarTitleDisplayMode(.inline)
        .task {
            do { live = try await state.api.browserLive(job: jobId) } catch { gone = true }
        }
    }

    private func takeOver() async {
        do { live = try await state.api.takeOverBrowserJob(job: jobId) } catch { gone = true }
    }
}
