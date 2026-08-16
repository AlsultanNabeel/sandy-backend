import SwiftUI

@MainActor
final class HabitsStore: LoadableStore {
    @Published var habits: [HabitItem] = []
    @Published var error = ""

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                let r = try await api.getHabits()
                withAnimation { habits = r.items }
                demo = r.demo
            } catch {
                if !error.isCancellation {
                    withAnimation { self.error = LanguageManager.shared.s("life.habits.loadError") }
                }
            }
        }
        loadTask = task
        await task.value
    }

    func add(api: APIClient, name: String) async throws {
        try await api.addHabit(name: name)
        await load(api: api)
    }

    /// إعادة تسمية عادة ثم إعادة جلب — يرمي عند الفشل ليتعامل الشيت معه.
    func rename(api: APIClient, habit: HabitItem, name: String) async throws {
        try await api.renameHabit(id: habit.id, name: name)
        await load(api: api)
    }

    /// حذف تفاؤلي فوري ثم مصالحة عند الفشل.
    func delete(api: APIClient, habit: HabitItem) {
        withAnimation { habits.removeAll { $0.id == habit.id } }
        Task { @MainActor in
            do {
                try await api.deleteHabit(id: habit.id)
            } catch {
                withAnimation { self.error = LanguageManager.shared.s("life.habits.deleteError") }
                await load(api: api)
            }
        }
    }

    func checkin(api: APIClient, habit: HabitItem) {
        guard !habit.doneToday else { return }
        Task { @MainActor in
            do {
                try await api.checkinHabit(name: habit.name)
                await load(api: api)
            } catch {
                withAnimation { self.error = LanguageManager.shared.s("life.habits.checkinError") }
            }
        }
    }

    func uncheckin(api: APIClient, habit: HabitItem) {
        guard habit.doneToday else { return }
        Task { @MainActor in
            do {
                try await api.uncheckinHabit(id: habit.id)
                await load(api: api)
            } catch {
                withAnimation { self.error = LanguageManager.shared.s("life.habits.checkinError") }
            }
        }
    }
}
