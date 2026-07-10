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
                if !error.isCancellation { notice = LanguageManager.shared.s("shopping.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة غرض ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, text: String, category: String) async -> Bool {
        do {
            try await api.addShopping(text: text, category: category)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("shopping.errorAdd")
            return false
        }
    }

    /// تعديل اسم/تصنيف الغرض ثم إعادة جلب. الباك-إند ما عنده PATCH للنص، فبنعمل
    /// التعديل كحذف للقديم + إضافة جديد (نفس النتيجة بنظر المستخدم).
    func update(api: APIClient, item: ShoppingItem, text: String, category: String) async -> Bool {
        do {
            try await api.addShopping(text: text, category: category)
            try await api.deleteShopping(id: item.id)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("shopping.errorEdit")
            return false
        }
    }

    /// شطب الغرض كـ"انشترى" مع سعره (الباك-إند بيضيفه لمصاريفك). ثم إعادة جلب.
    func buy(api: APIClient, item: ShoppingItem, price: Double) async -> Bool {
        do {
            try await api.checkShopping(id: item.id, price: price)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("shopping.errorBuy")
            return false
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, item: ShoppingItem) {
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        items.remove(at: idx)
        Task { @MainActor in
            do {
                try await api.deleteShopping(id: item.id)
            } catch {
                items.insert(item, at: min(idx, items.count))
                notice = LanguageManager.shared.s("shopping.errorDelete")
            }
        }
    }
}
