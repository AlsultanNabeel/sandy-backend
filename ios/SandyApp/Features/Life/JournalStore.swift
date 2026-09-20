import SwiftUI

@MainActor
final class JournalStore: LoadableStore {
    @Published var entries: [JournalEntry] = []
    @Published var error = ""

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let gen = beginLoad()
        let cacheKey = "journal"
        if !hasSnapshot, let cached = DiskCache.load(CachedList<CachedJournalEntry>.self, key: cacheKey,
                                                     userId: api.currentUserId) {
            entries = cached.items.map(\.model)
            demo = cached.demo
            hasSnapshot = true
        }
        let task = Task { @MainActor in
            defer { endLoad(gen) }
            do {
                let r = try await api.getJournal()
                guard isCurrentLoad(gen) else { return }
                withAnimation { entries = r.items }
                demo = r.demo
                markLoaded()
                DiskCache.save(CachedList(items: r.items.map { CachedJournalEntry($0) }, demo: r.demo),
                               key: cacheKey, userId: api.currentUserId)
                if !r.demo { SpotlightIndexer.indexJournal(r.items) }
            } catch {
                failLoad(error, generation: gen) {
                    withAnimation { self.error = LanguageManager.shared.s("life.journal.loadError") }
                }
            }
        }
        loadTask = task
        await task.value
    }

    func add(api: APIClient, text: String) async throws {
        try await api.addJournalEntry(text: text)
        await load(api: api)
    }

    /// تعديل نص خاطرة ثم إعادة جلب — يرمي عند الفشل ليتعامل الشيت معه.
    func update(api: APIClient, id: String, text: String) async throws {
        try await api.updateJournalEntry(id: id, text: text)
        await load(api: api)
    }

    /// حذف تفاؤلي فوري ثم مصالحة عند الفشل.
    func delete(api: APIClient, entry: JournalEntry) {
        withAnimation { entries.removeAll { $0.id == entry.id } }
        Task { @MainActor in
            do {
                try await api.deleteJournalEntry(id: entry.id)
            } catch {
                withAnimation { self.error = LanguageManager.shared.s("life.journal.deleteError") }
                await load(api: api)
            }
        }
    }
}
