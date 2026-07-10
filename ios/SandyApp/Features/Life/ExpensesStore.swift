import SwiftUI

@MainActor
final class ExpensesStore: LoadableStore {
    @Published var items: [ExpenseItem] = []
    @Published var summary = ExpensesSummary(total: 0, count: 0)
    @Published var error = ""

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                let r = try await api.getExpenses()
                withAnimation { items = r.items }
                summary = r.summary
                demo = r.demo
            } catch {
                if !error.isCancellation { withAnimation { self.error = LanguageManager.shared.s("life.expenses.loadError") } }
            }
        }
        loadTask = task
        await task.value
    }

    func add(api: APIClient, amount: Double, note: String, category: String) async throws {
        try await api.addExpense(amount: amount, note: note, category: category)
        await load(api: api)
    }

    /// تعديل مصروف ثم إعادة جلب — يرمي عند الفشل ليتعامل الشيت معه.
    func update(api: APIClient, id: String, amount: Double, note: String, category: String) async throws {
        try await api.updateExpense(id: id, amount: amount, note: note, category: category)
        await load(api: api)
    }

    /// حذف تفاؤلي للعنصر والمجموع معًا (يبان حيّ)، ثم مصالحة مع السيرفر بإعادة جلب.
    func delete(api: APIClient, item: ExpenseItem) {
        withAnimation { items.removeAll { $0.id == item.id } }
        summary = ExpensesSummary(total: max(0, summary.total - item.amount),
                                  count: max(0, summary.count - 1))
        Task { @MainActor in
            do {
                try await api.deleteExpense(id: item.id)
            } catch {
                withAnimation { self.error = LanguageManager.shared.s("life.expenses.deleteError") }
            }
            await load(api: api)   // مصالحة المجموع/القائمة مع السيرفر بالحالتين
        }
    }
}
