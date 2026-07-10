import SwiftUI

@MainActor
final class MemoryStore: LoadableStore {
    @Published var facts: [MemoryFact] = []

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                facts = try await api.getMemory()
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("memory.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة معلومة ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, text: String) async -> Bool {
        do {
            try await api.addMemory(text: text)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("memory.errorAdd")
            return false
        }
    }

    /// تعديل نص معلومة ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة.
    func update(api: APIClient, id: String, text: String) async -> Bool {
        do {
            try await api.updateMemory(id: id, text: text)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("memory.errorEdit")
            return false
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, fact: MemoryFact) {
        guard let idx = facts.firstIndex(where: { $0.id == fact.id }) else { return }
        facts.remove(at: idx)
        Task { @MainActor in
            do {
                try await api.deleteMemory(id: fact.id)
            } catch {
                facts.insert(fact, at: min(idx, facts.count))
                notice = LanguageManager.shared.s("memory.errorDelete")
            }
        }
    }
}
