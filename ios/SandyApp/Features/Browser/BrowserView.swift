import SwiftUI

/// The browser, from Profile: the emergency stop, «Sandy's browser» for each open fill, and
/// the sites she may open, each with what she may do there and «طلّعها» for his sign-in.
struct BrowserView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store = BrowserStore()

    var body: some View {
        List {
            if !store.notice.isEmpty {
                SandyNotice(store.notice, kind: .gentleWarning).listRowBackground(Color.clear)
            }
            Section {
                StopAllButton(stopped: store.stopped) { value in
                    Task { await store.setStopped(value, api: state.api) }
                }
            } footer: {
                Text(lang.s("browser.stopFooter"))
            }
            if !store.jobs.isEmpty {
                Section(lang.s("browser.live")) {
                    ForEach(store.jobs) { job in
                        NavigationLink {
                            LiveBrowserView(jobId: job.id)
                        } label: {
                            LabeledContent(job.site, value: lang.s("browser.status." + job.status))
                        }
                    }
                }
            }
            Section {
                if store.sites.isEmpty && !store.loading {
                    Text(lang.s("browser.empty"))
                        .font(Theme.Typography.body)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
                ForEach(store.sites) { site in
                    SiteRow(site: site, store: store)
                }
            } header: {
                Text(lang.s("browser.sites"))
            } footer: {
                Text(lang.s("browser.levelsFooter"))
            }
        }
        .overlay { if store.loading && store.sites.isEmpty { ProgressView() } }
        .navigationTitle(lang.s("browser.title"))
        .navigationBarTitleDisplayMode(.inline)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
    }
}

/// «وقّفي كل شي», or «رجّعي كل شي» once stopped: one tap either way.
struct StopAllButton: View {
    @EnvironmentObject var lang: LanguageManager
    let stopped: Bool
    let change: (Bool) -> Void

    var body: some View {
        Button(role: stopped ? nil : .destructive) {
            change(!stopped)
        } label: {
            Label(lang.s(stopped ? "browser.resume" : "browser.stop"),
                  systemImage: stopped ? "play.circle.fill" : "stop.circle.fill")
                .font(Theme.Typography.headline)
        }
        .accessibilityHint(lang.s(stopped ? "browser.resumeHint" : "browser.stopHint"))
    }
}

private struct SiteRow: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    let site: BrowserSite
    @ObservedObject var store: BrowserStore

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            HStack {
                Text(site.site).font(Theme.Typography.headline).lineLimit(1)
                Spacer(minLength: 0)
                if site.signedIn {
                    Text(lang.s("browser.signedIn"))
                        .font(Theme.Typography.caption.weight(.semibold))
                        .foregroundColor(Theme.Colors.accent)
                }
            }
            Picker(lang.s("browser.level"), selection: Binding(
                get: { site.level },
                set: { new in Task { await store.setLevel(new, site: site.site, api: state.api) } })) {
                ForEach(BrowserSite.levels, id: \.self) { level in
                    Text(lang.s("browser.level." + level)).tag(level)
                }
            }
            .pickerStyle(.segmented)
            if site.signedIn {
                Button(lang.s("browser.signOut"), role: .destructive) {
                    Task { await store.signOut(site: site.site, api: state.api) }
                }
                .font(Theme.Typography.caption)
            }
        }
        .padding(.vertical, Theme.Spacing.xs)
    }
}
