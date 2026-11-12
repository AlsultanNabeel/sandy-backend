import SwiftUI
import WebKit

/// A web page in the app, on a store of its own that lives only as long as the screen: what he
/// does there never mixes with another site or another account.
struct BrowserWebView: UIViewRepresentable {
    let url: URL
    let store: WKWebsiteDataStore
    var onLoad: ((WKWebView) -> Void)?
    /// A live stream that plays as it opens, with no tap (Steel's view of a fill is a video).
    var playsAtOnce = false

    func makeCoordinator() -> Coordinator { Coordinator(onLoad: onLoad) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = store
        if playsAtOnce {
            config.allowsInlineMediaPlayback = true
            config.mediaTypesRequiringUserActionForPlayback = []
            // Low Power Mode refuses even a muted autoplay (seen on iOS 27, 12 Nov 2026): Steel's
            // player then waits for its own «Play Video», and unpressed it gives up as «Browser
            // Disconnected». The app starts it for him, from a world of its own: what the app does
            // counts as his. Not by pressing the button: after that press the player draws its
            // first frame and then covers it with «Connecting…» for good. The video's «canplay»
            // once more takes it down its usual way, which takes the cover off.
            let world = WKContentWorld.defaultClient
            config.userContentController.add(context.coordinator, contentWorld: world, name: Coordinator.blocked)
            config.userContentController.addUserScript(WKUserScript(
                source: Coordinator.watchForPlay, injectionTime: .atDocumentEnd, forMainFrameOnly: true, in: world))
        }
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

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        weak var view: WKWebView?
        var loaded: URL?
        let onLoad: ((WKWebView) -> Void)?

        /// Steel's player shows `#playButton` when its autoplay was refused; told once per button.
        static let blocked = "autoplayBlocked"
        static let watchForPlay = """
        (() => { const told = new WeakSet();
          const look = () => { const b = document.getElementById("playButton");
            if (b && !told.has(b)) { told.add(b); window.webkit.messageHandlers.\(blocked).postMessage(1); } };
          new MutationObserver(look).observe(document.documentElement, { childList: true, subtree: true });
          look(); })();
        """

        init(onLoad: ((WKWebView) -> Void)?) { self.onLoad = onLoad }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation?) {
            onLoad?(webView)
        }

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            view?.callAsyncJavaScript("document.querySelector('video')?.dispatchEvent(new Event('canplay'))",
                                      arguments: [:], in: nil, in: .defaultClient)
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
/// and the view is his to drive. Once the fill is no longer open (done, stopped, closed by the
/// gate or the sweep) the view gives way to a line in his language and a way back, never
/// Steel's own «Browser Disconnected» page: it asks every few seconds while it is open.
struct LiveBrowserView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let jobId: String
    static let checkEvery: Duration = .seconds(5)
    @State private var live: BrowserLive?
    @State private var gone = false
    /// The fill as the server has it: the question it waits on, shown here too.
    @State private var job: BrowserJobView?
    @State private var answer = ""
    @State private var answering = false
    @State private var store = WKWebsiteDataStore.nonPersistent()

    var body: some View {
        VStack(spacing: 0) {
            if let live, let url = URL(string: live.url) {
                BrowserWebView(url: url, store: store, playsAtOnce: true)
                    .allowsHitTesting(live.control)
                if let ask = job?.ask { asking(ask) }
                Button {
                    Task { await (live.control ? giveBack() : takeOver()) }
                } label: {
                    Label(lang.s(live.control ? "browser.giveBack" : "browser.takeOver"),
                          systemImage: live.control ? "arrow.uturn.backward.circle.fill" : "hand.raised.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .padding(Theme.Spacing.md)
            } else if gone, let ask = job?.ask {
                // It closed asking for what it needs: asked here as in the chat.
                asking(ask).frame(maxHeight: .infinity)
            } else if gone {
                VStack(spacing: Theme.Spacing.md) {
                    Image(systemName: "checkmark.circle")
                        .font(.largeTitle)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .accessibilityHidden(true)
                    Text(lang.s("browser.liveGone"))
                        .font(Theme.Typography.body)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .multilineTextAlignment(.center)
                    Button(lang.s("browser.back")) { dismiss() }
                        .buttonStyle(.borderedProminent)
                }
                .padding(Theme.Spacing.lg)
                .frame(maxHeight: .infinity)
            } else {
                ProgressView().frame(maxHeight: .infinity)
            }
        }
        .navigationTitle(lang.s("browser.live"))
        .navigationBarTitleDisplayMode(.inline)
        .task {
            do { live = try await state.api.browserLive(job: jobId) } catch { gone = true }
            job = try? await state.api.browserJob(job: jobId)
            // While it is shown: its question as it comes, and the fill closed is a line and a
            // way back, not Steel's page.
            while !gone, !Task.isCancelled {
                try? await Task.sleep(for: Self.checkEvery)
                guard let now = try? await state.api.browserJob(job: jobId) else { continue }
                job = now
                if !now.open { gone = true }
            }
        }
    }

    /// The question the fill waits on, as the chat asked it: «آه» and «لا» for its send, a line to
    /// answer for what it needs. The answer goes into its conversation as his own message, on
    /// the chat's own path (`/api/agent`), so it is taken once whichever answers first.
    private func asking(_ ask: BrowserJobView.Ask) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Text(ask.text)
                .font(Theme.Typography.body)
                .fixedSize(horizontal: false, vertical: true)
            if ask.kind == "confirm" {
                HStack(spacing: Theme.Spacing.sm) {
                    Button(lang.s("browser.askYes")) { Task { await reply(lang.s("browser.askYesSaid")) } }
                        .buttonStyle(.borderedProminent)
                    Button(lang.s("browser.askNo")) { Task { await reply(lang.s("browser.askNoSaid")) } }
                        .buttonStyle(.bordered)
                }
            } else {
                HStack(spacing: Theme.Spacing.sm) {
                    TextField(lang.s("browser.askAnswer"), text: $answer)
                        .textFieldStyle(.roundedBorder)
                    Button(lang.s("browser.askSend")) {
                        let said = answer.trimmingCharacters(in: .whitespacesAndNewlines)
                        Task { await reply(said) }
                    }
                    .disabled(answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .disabled(answering)
        .padding(Theme.Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .liquidGlass(cornerRadius: Theme.Radius.bubble, tint: 0.06)
        .padding(.horizontal, Theme.Spacing.md)
    }

    /// His answer, said in the fill's conversation as he would say it there: his line kept, the
    /// turn run, her reply kept.
    private func reply(_ text: String) async {
        guard let thread = job?.thread, !thread.isEmpty, !text.isEmpty, !answering else { return }
        answering = true
        defer { answering = false }
        await state.api.say(text, in: thread)
        answer = ""
        if job?.ask?.kind == "needs" {
            // What it needed starts a new fill, its own to watch from the chat: this one is done.
            job = nil
            gone = true
            return
        }
        job = try? await state.api.browserJob(job: jobId)
        if job?.open != true { gone = true }
    }

    private func takeOver() async {
        do { live = try await state.api.takeOverBrowserJob(job: jobId) } catch { gone = true }
    }

    /// The page back to Sandy: she goes on, and the view is to watch again.
    private func giveBack() async {
        do {
            try await state.api.giveBackBrowserJob(job: jobId)
            live = try await state.api.browserLive(job: jobId)
        } catch { gone = true }
    }
}
