import SwiftUI

/// The browser, from Profile: the emergency stop, «Sandy's browser» for each open fill, and
/// the sites she may open, each with what she may do there and «طلّعها» for his sign-in;
/// «أضف موقع» adds one by its name. Opened from a refusal in Sandy's reply
/// (`sandy://browser/site?site=`) on that site: shown marked, or offered to add when not listed.
/// What she may do is his alone to change, here.
struct BrowserView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store = BrowserStore()
    var focus: String? = nil
    @State private var adding: String?

    var body: some View {
        ScrollViewReader { proxy in
            list
                .task {
                    await store.load(api: state.api)
                    guard let focus else { return }
                    if store.sites.contains(where: { $0.site == focus }) {
                        withAnimation { proxy.scrollTo(focus, anchor: .center) }
                    } else {
                        adding = focus
                    }
                }
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button { adding = "" } label: { Label(lang.s("browser.addSite"), systemImage: "plus") }
            }
        }
        .sheet(item: Binding(get: { adding.map(AddingSite.init) }, set: { adding = $0?.id })) { item in
            AddSiteSheet(typed: item.id, store: store)
                .environmentObject(state)
                .environmentObject(lang)
        }
    }

    private var list: some View {
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
                        .id(site.site)
                        .listRowBackground(site.site == focus ? Theme.Colors.accent.opacity(0.12) : nil)
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
        .refreshable { await store.load(api: state.api) }
    }
}

private struct AddingSite: Identifiable { let id: String }

/// «أضف موقع»: the domain and what she may do there, read only unless he picks another.
private struct AddSiteSheet: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    @State var typed: String
    @ObservedObject var store: BrowserStore
    @State private var level = BrowserSite.read
    @State private var problem = ""
    @State private var saving = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(lang.s("browser.siteName"), text: $typed, prompt: Text(verbatim: "example.com"))
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .environment(\.layoutDirection, .leftToRight)
                    Picker(lang.s("browser.level"), selection: $level) {
                        ForEach(BrowserSite.levels, id: \.self) { level in
                            Text(lang.s("browser.level." + level)).tag(level)
                        }
                    }
                    .pickerStyle(.segmented)
                } footer: {
                    VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                        if !problem.isEmpty {
                            Text(problem).foregroundColor(Theme.Colors.danger)
                        }
                        Text(lang.s("browser.levelsFooter"))
                        Text(lang.s("browser.addFooter"))
                    }
                }
            }
            .navigationTitle(lang.s("browser.addSite"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("browser.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.s("browser.add")) {
                        saving = true
                        Task {
                            let said = await store.addSite(typed, level: level, api: state.api)
                            saving = false
                            if let said { problem = said } else { dismiss() }
                        }
                    }
                    .disabled(saving || BrowserSite.name(of: typed).isEmpty)
                }
            }
        }
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
