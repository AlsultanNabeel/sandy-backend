import SwiftUI

@MainActor
final class ShoppingStore: LoadableStore {
    @Published var items: [ShoppingItem] = []

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                items = try await api.getShopping()
            } catch {
                if !error.isCancellation { notify("shopping.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة غرض ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, text: String, category: String) async -> Bool {
        do {
            try await api.addShopping(text: text, category: category)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("shopping.errorAdd")
            return false
        }
    }

    /// تعديل اسم/تصنيف الغرض ثم إعادة جلب. الباك-إند ما عنده PATCH للنص، فبنعمل
    /// التعديل كحذف للقديم + إضافة جديد (نفس النتيجة بنظر المستخدم).
    func update(api: APIClient, item: ShoppingItem, text: String, category: String) async -> Bool {
        do {
            try await api.addShopping(text: text, category: category)
            try await api.deleteShopping(id: item.id)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("shopping.errorEdit")
            return false
        }
    }

    /// شطب الغرض كـ"انشترى" مع سعره (الباك-إند بيضيفه لمصاريفك). ثم إعادة جلب.
    func buy(api: APIClient, item: ShoppingItem, price: Double) async -> Bool {
        do {
            try await api.checkShopping(id: item.id, price: price)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("shopping.errorBuy")
            return false
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, item: ShoppingItem) {
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        optimistic(
            "shopping.errorDelete",
            apply: { self.items.remove(at: idx) },
            rollback: { self.items.insert(item, at: min(idx, self.items.count)) },
            call: { try await api.deleteShopping(id: item.id) }
        )
    }
}
