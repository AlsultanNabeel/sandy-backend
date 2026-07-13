import SwiftUI

@MainActor
final class GiftsStore: LoadableStore {
    @Published var gifts: [DigitalGift] = []

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                gifts = try await api.getGifts()
            } catch {
                if !error.isCancellation { notify("gifts.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة هدية ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, draft: GiftDraft) async -> Bool {
        do {
            try await api.addGift(kind: draft.kind.rawValue,
                                  recipient: draft.recipient,
                                  occasion: draft.occasion,
                                  content: draft.content,
                                  scheduledAt: draft.scheduledAt)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("gifts.errorAdd")
            return false
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, gift: DigitalGift) {
        guard let idx = gifts.firstIndex(where: { $0.id == gift.id }) else { return }
        optimistic(
            "gifts.errorDelete",
            apply: { self.gifts.remove(at: idx) },
            rollback: { self.gifts.insert(gift, at: min(idx, self.gifts.count)) },
            call: { try await api.deleteGift(id: gift.id) }
        )
    }
}
