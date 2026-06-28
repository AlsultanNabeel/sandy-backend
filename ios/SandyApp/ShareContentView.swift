import SwiftUI

/// شاشة "محتوى يهمّك" — ساندي بتجمع محتوى من اهتماماتك اللي رصدتها من حديثك معها
/// (عبر `/api/share/suggest`)، وبتخليك تحفظ أي بطاقة تعجبك أو تشيلها. مبدّل علوي
/// بين المقترح والمحفوظ. نمط الستور المعتمد: الجلب بمهمة يملكها الستور، فإلغاء
/// إيماءة الواجهة ما بيلغيه.
struct ShareContentView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = ShareContentStore()
    @State private var segment: Segment = .suggested

    /// المقطع المعروض — مقترح إلك / المحفوظ.
    enum Segment: Hashable { case suggested, saved }

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                segmentPicker

                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                content
            }
        }
        .navigationTitle(lang.s("tabs.shareContent"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                if segment == .suggested {
                    SandyButton(title: lang.s("shareContent.refresh"),
                                systemImage: "arrow.clockwise",
                                style: .secondary) {
                        Task { await store.loadSuggested(api: state.api) }
                    }
                }
            }
        }
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .animation(.spring(response: 0.45, dampingFraction: 0.85), value: store.saved.map(\.id))
        .task {
            await store.loadSuggested(api: state.api)
            await store.loadSaved(api: state.api)
        }
        .refreshable {
            if segment == .suggested { await store.loadSuggested(api: state.api) }
            else { await store.loadSaved(api: state.api) }
        }
    }

    private var segmentPicker: some View {
        Picker("", selection: $segment) {
            Text(lang.s("shareContent.seg.suggested")).tag(Segment.suggested)
            Text(lang.s("shareContent.seg.saved")).tag(Segment.saved)
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, Theme.Spacing.sm)
    }

    @ViewBuilder
    private var content: some View {
        ScrollView {
            VStack(spacing: Theme.Spacing.md) {
                switch segment {
                case .suggested: suggestedBody
                case .saved:     savedBody
                }
            }
            .padding(Theme.Spacing.md)
            .padding(.bottom, Theme.Spacing.xxl + Theme.Spacing.xl)
        }
    }

    // MARK: - مقترح إلك

    @ViewBuilder
    private var suggestedBody: some View {
        if store.loadingSuggested {
            ProgressView().tint(Theme.Colors.accent).padding(.top, Theme.Spacing.xxl)
        } else if store.topic.isEmpty {
            emptyState(icon: "sparkles",
                       text: lang.s("shareContent.empty.hint"))
        } else if store.suggested.isEmpty {
            emptyState(icon: "tray",
                       text: lang.s("shareContent.empty.results"))
        } else {
            header
            ForEach(store.suggested) { item in
                contentCard(item, saved: false)
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            Text(lang.s("shareContent.intro"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
            Text("\(lang.s("shareContent.topic")) « \(store.topic) »")
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.accent)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - المحفوظ

    @ViewBuilder
    private var savedBody: some View {
        if store.loadingSaved {
            ProgressView().tint(Theme.Colors.accent).padding(.top, Theme.Spacing.xxl)
        } else if store.saved.isEmpty {
            emptyState(icon: "bookmark", text: lang.s("shareContent.empty.saved"))
        } else {
            ForEach(store.saved) { item in
                contentCard(item, saved: true)
            }
        }
    }

    // MARK: - بطاقة محتوى

    private func contentCard(_ item: SharedContentItem, saved: Bool) -> some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                Text(item.displayTitle)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if !item.text.isEmpty {
                    Text(item.text)
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .lineLimit(3)
                }

                HStack(spacing: Theme.Spacing.md) {
                    if let url = item.link {
                        Link(destination: url) {
                            Label(prettyHost(item.url), systemImage: "link")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.accent)
                                .lineLimit(1)
                        }
                    }

                    Spacer(minLength: 0)

                    if saved {
                        Button {
                            store.remove(api: state.api, item: item)
                        } label: {
                            Label(lang.s("shareContent.remove"), systemImage: "trash")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.danger)
                        }
                        .buttonStyle(.plain)
                    } else {
                        Button {
                            Task { await store.save(api: state.api, item: item) }
                        } label: {
                            Label(lang.s(store.isSaved(item) ? "shareContent.saved"
                                                             : "shareContent.save"),
                                  systemImage: store.isSaved(item) ? "checkmark.circle.fill"
                                                                   : "bookmark")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.accent)
                        }
                        .buttonStyle(.plain)
                        .disabled(store.isSaved(item))
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func emptyState(icon: String, text: String) -> some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: icon)
                .font(.system(size: Theme.Icon.xl))
                .foregroundColor(Theme.Colors.accent.opacity(0.5))
            Text(text)
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, Theme.Spacing.xxl)
        .padding(.horizontal, Theme.Spacing.lg)
    }

    /// اسم النطاق فقط للعرض (بدون البروتوكول والمسار الطويل).
    private func prettyHost(_ s: String) -> String {
        URL(string: s)?.host?.replacingOccurrences(of: "www.", with: "") ?? s
    }
}

// MARK: - الستور (مصدر الحقيقة للمحتوى المقترح والمحفوظ)

@MainActor
final class ShareContentStore: ObservableObject {
    @Published var suggested: [SharedContentItem] = []
    @Published var saved: [SharedContentItem] = []
    @Published var topic = ""
    @Published var loadingSuggested = false
    @Published var loadingSaved = false
    @Published var notice = ""

    private var suggestTask: Task<Void, Never>?
    private var savedTask: Task<Void, Never>?

    /// عنصر محفوظ مسبقًا؟ نطابق بالرابط (أو العنوان لو ما في رابط).
    func isSaved(_ item: SharedContentItem) -> Bool {
        saved.contains { ($0.url.isEmpty ? $0.displayTitle == item.displayTitle
                                         : $0.url == item.url) }
    }

    func loadSuggested(api: APIClient) async {
        suggestTask?.cancel()
        let task = Task { @MainActor in
            loadingSuggested = true
            defer { loadingSuggested = false }
            do {
                let r = try await api.shareContentSuggest()
                topic = r.topic
                suggested = r.items
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("shareContent.error") }
            }
        }
        suggestTask = task
        await task.value
    }

    func loadSaved(api: APIClient) async {
        savedTask?.cancel()
        let task = Task { @MainActor in
            loadingSaved = true
            defer { loadingSaved = false }
            do {
                saved = try await api.shareContentSaved()
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("shareContent.error") }
            }
        }
        savedTask = task
        await task.value
    }

    /// حفظ بطاقة ثم إعادة جلب المحفوظ ليتحدّث وسم "اتحفظت".
    func save(api: APIClient, item: SharedContentItem) async {
        guard !isSaved(item) else { return }
        do {
            try await api.shareContentSave(item: item, topic: topic)
            await loadSaved(api: api)
        } catch {
            notice = LanguageManager.shared.s("shareContent.error")
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func remove(api: APIClient, item: SharedContentItem) {
        guard let idx = saved.firstIndex(where: { $0.id == item.id }) else { return }
        saved.remove(at: idx)
        Task { @MainActor in
            do {
                try await api.shareContentDelete(id: item.id)
            } catch {
                saved.insert(item, at: min(idx, saved.count))
                notice = LanguageManager.shared.s("shareContent.error")
            }
        }
    }
}

// MARK: - النموذج

/// بطاقة محتوى مقترح أو محفوظ. المقترح بلا `serverId` (لسا ما اتحفظ)؛ المحفوظ
/// بيحمل `id` من الباك-إند للحذف. `id` للعرض ثابت داخل الجلسة.
struct SharedContentItem: Identifiable {
    let id: String
    let title: String
    let url: String
    let text: String

    /// عنوان العرض — لو فاضي نرجع للرابط.
    var displayTitle: String { title.isEmpty ? url : title }
    var link: URL? { url.isEmpty ? nil : URL(string: url) }
}

// MARK: - نداءات الباك-إند

extension APIClient {
    // GET /api/share/suggest → {"topic","items":[{title,url,text,published_date}]}
    func shareContentSuggest() async throws -> (topic: String, items: [SharedContentItem]) {
        let r = try await request("/api/share/suggest")
        let topic = r["topic"] as? String ?? ""
        let items = (r["items"] as? [[String: Any]] ?? []).map { row in
            SharedContentItem(id: UUID().uuidString,
                              title: row["title"] as? String ?? "",
                              url: row["url"] as? String ?? "",
                              text: row["text"] as? String ?? "")
        }
        return (topic, items)
    }

    // GET /api/share/saved → {"items":[{id,title,url,text,topic}]}
    func shareContentSaved() async throws -> [SharedContentItem] {
        let r = try await request("/api/share/saved")
        return (r["items"] as? [[String: Any]] ?? []).compactMap { row in
            guard let id = row["id"] as? String, !id.isEmpty else { return nil }
            return SharedContentItem(id: id,
                                     title: row["title"] as? String ?? "",
                                     url: row["url"] as? String ?? "",
                                     text: row["text"] as? String ?? "")
        }
    }

    // POST /api/share/saved {title,url,text,topic} → {"ok":true,"id"}
    func shareContentSave(item: SharedContentItem, topic: String) async throws {
        _ = try await request("/api/share/saved", method: "POST", body: [
            "title": item.title,
            "url": item.url,
            "text": item.text,
            "topic": topic,
        ])
    }

    // DELETE /api/share/saved/<id>
    func shareContentDelete(id: String) async throws {
        _ = try await request("/api/share/saved/\(id)", method: "DELETE")
    }
}
