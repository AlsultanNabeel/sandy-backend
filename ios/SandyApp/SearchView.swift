import SwiftUI

/// نوع البحث — ويب (Exa) أو أماكن (Google Places).
enum SearchKind: Hashable { case web, places }

/// تبويب البحث — بحث ويب خارجي وأماكن عبر `/api/research`، بنتائج منظّمة
/// (عناوين/روابط/مقتطفات للويب؛ اسم/تقييم/عنوان للأماكن). نمط الستور المعتمد:
/// الجلب يجري في مهمة يملكها الستور، فإلغاء إيماءة الواجهة ما يلغيه.
struct SearchView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = SearchStore()
    @State private var query = ""
    @State private var kind: SearchKind = .web
    @FocusState private var fieldFocused: Bool

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if store.demo { DemoBanner() }

                searchBar
                kindPicker

                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                results
            }
        }
        .navigationTitle(lang.s("tabs.search"))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
    }

    // MARK: - حقل البحث

    private var searchBar: some View {
        HStack(spacing: Theme.Spacing.sm) {
            Image(systemName: "magnifyingglass")
                .foregroundColor(Theme.Colors.secondaryText)
            TextField(lang.s("search.placeholder"), text: $query)
                .textFieldStyle(.plain)
                .focused($fieldFocused)
                .submitLabel(.search)
                .onSubmit { runSearch() }
            if !query.isEmpty {
                Button { query = "" } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(Theme.Colors.secondaryText)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(Theme.Spacing.sm)
        .background(RoundedRectangle(cornerRadius: Theme.Radius.control).fill(.ultraThinMaterial))
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, Theme.Spacing.sm)
    }

    private var kindPicker: some View {
        Picker("", selection: $kind) {
            Text(lang.s("search.kind.web")).tag(SearchKind.web)
            Text(lang.s("search.kind.places")).tag(SearchKind.places)
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, Theme.Spacing.sm)
        // تبديل النوع يعيد البحث بنفس الاستعلام لو في استعلام.
        .onChange(of: kind) { _ in runSearch(keepKeyboard: true) }
    }

    // MARK: - النتائج

    @ViewBuilder
    private var results: some View {
        ScrollView {
            VStack(spacing: Theme.Spacing.md) {
                if store.loading {
                    ProgressView().tint(Theme.Colors.accent).padding(.top, Theme.Spacing.xxl)
                } else if !store.hasSearched {
                    hintView
                } else if store.isEmpty(kind) {
                    Text(lang.s("search.empty"))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .padding(.top, Theme.Spacing.xxl)
                } else {
                    switch kind {
                    case .web:    ForEach(store.web) { WebRow(result: $0) }
                    case .places: ForEach(store.places) { PlaceRow(result: $0) }
                    }
                }
            }
            .padding(Theme.Spacing.md)
            .padding(.bottom, Theme.Spacing.xxl + Theme.Spacing.xl)
        }
        .refreshable { await store.search(api: state.api, q: trimmed, kind: kind) }
    }

    private var hintView: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "globe.middle.east.fill")
                .font(.system(size: 44))
                .foregroundColor(Theme.Colors.accent.opacity(0.6))
            Text(lang.s("search.hint"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
        }
        .padding(.top, Theme.Spacing.xxl)
        .padding(.horizontal, Theme.Spacing.lg)
    }

    private var trimmed: String {
        query.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func runSearch(keepKeyboard: Bool = false) {
        guard !trimmed.isEmpty else { return }
        if !keepKeyboard { fieldFocused = false }
        Task { await store.search(api: state.api, q: trimmed, kind: kind) }
    }
}

// MARK: - الستور (مصدر الحقيقة للنتائج)

@MainActor
final class SearchStore: ObservableObject {
    @Published var web: [WebResult] = []
    @Published var places: [PlaceResult] = []
    @Published var loading = false
    @Published var demo = false
    @Published var notice = ""
    /// صار في بحث واحد على الأقل (نميّز "ابدأ بالبحث" عن "ما في نتائج").
    @Published var hasSearched = false

    private var searchTask: Task<Void, Never>?

    func isEmpty(_ kind: SearchKind) -> Bool {
        kind == .web ? web.isEmpty : places.isEmpty
    }

    /// بحث مملوك للستور وينتظره — يصلح للإرسال والـ `.refreshable` معاً.
    func search(api: APIClient, q: String, kind: SearchKind) async {
        guard !q.isEmpty else { return }
        searchTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            notice = ""
            defer { loading = false }
            do {
                switch kind {
                case .web:
                    let r = try await api.researchWeb(q: q)
                    web = r.items; demo = r.demo
                case .places:
                    let r = try await api.researchPlaces(q: q)
                    places = r.items; demo = r.demo
                }
                hasSearched = true
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("search.error") }
            }
        }
        searchTask = task
        await task.value
    }
}

// MARK: - صف نتيجة ويب

private struct WebRow: View {
    let result: WebResult

    var body: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(result.title.isEmpty ? result.url : result.title)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                    .lineLimit(2)

                if !result.text.isEmpty {
                    Text(result.text)
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .lineLimit(3)
                }

                if let url = URL(string: result.url), !result.url.isEmpty {
                    Link(destination: url) {
                        HStack(spacing: 4) {
                            Image(systemName: "link")
                            Text(prettyHost(result.url)).lineLimit(1)
                        }
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.accent)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    /// اسم النطاق فقط للعرض (بدون البروتوكول والمسار الطويل).
    private func prettyHost(_ s: String) -> String {
        URL(string: s)?.host?.replacingOccurrences(of: "www.", with: "") ?? s
    }
}

// MARK: - صف نتيجة مكان

private struct PlaceRow: View {
    @EnvironmentObject var lang: LanguageManager
    let result: PlaceResult

    var body: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                HStack {
                    Text(result.name)
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                        .lineLimit(2)
                    Spacer(minLength: 0)
                    if result.rating > 0 {
                        HStack(spacing: 2) {
                            Image(systemName: "star.fill").font(.caption2)
                            Text(String(format: "%.1f", result.rating)).monospacedDigit()
                        }
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.warn)
                    }
                }

                if !result.address.isEmpty {
                    Text(result.address)
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .lineLimit(2)
                }

                HStack(spacing: Theme.Spacing.sm) {
                    if !result.openNow.isEmpty {
                        Text(result.openNow)
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.success)
                    }
                    if !result.priceLevel.isEmpty {
                        Text(result.priceLevel)
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                }

                HStack(spacing: Theme.Spacing.md) {
                    if let u = URL(string: result.mapsUrl), !result.mapsUrl.isEmpty {
                        Link(destination: u) {
                            Label(lang.s("search.places.map"), systemImage: "map.fill")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.accent)
                        }
                    }
                    if let u = URL(string: "tel:\(result.phone)"), !result.phone.isEmpty {
                        Link(destination: u) {
                            Label(lang.s("search.places.call"), systemImage: "phone.fill")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.accent)
                        }
                    }
                    if let u = URL(string: result.website), !result.website.isEmpty {
                        Link(destination: u) {
                            Label(lang.s("search.places.site"), systemImage: "safari.fill")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.accent)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
