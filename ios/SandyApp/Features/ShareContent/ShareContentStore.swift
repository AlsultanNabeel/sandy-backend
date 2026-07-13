import SwiftUI

@MainActor
final class ShareContentStore: LoadableStore {
    @Published var suggested: [SharedContentItem] = []
    @Published var saved: [SharedContentItem] = []
    @Published var topic = ""
    @Published var loadingSuggested = false
    @Published var loadingSaved = false

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
                if !error.isCancellation { notify("shareContent.error") }
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
                if !error.isCancellation { notify("shareContent.error") }
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
            notify("shareContent.error")
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func remove(api: APIClient, item: SharedContentItem) {
        guard let idx = saved.firstIndex(where: { $0.id == item.id }) else { return }
        optimistic(
            "shareContent.error",
            apply: { self.saved.remove(at: idx) },
            rollback: { self.saved.insert(item, at: min(idx, self.saved.count)) },
            call: { try await api.shareContentDelete(id: item.id) }
        )
    }
}
