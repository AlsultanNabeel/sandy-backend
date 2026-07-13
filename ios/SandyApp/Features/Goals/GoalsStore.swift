import SwiftUI

@MainActor
final class GoalsStore: LoadableStore {
    @Published var goals: [GoalItem] = []

    private var loadTask: Task<Void, Never>?

    /// الأهداف النشطة ثم المكتملة (للعرض المقسوم).
    var active: [GoalItem] { goals.filter { !$0.isDone } }
    var done: [GoalItem] { goals.filter { $0.isDone } }

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                goals = try await api.getGoals()
            } catch {
                if !error.isCancellation { notify("goals.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة هدف ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, text: String, deadline: String) async -> Bool {
        do {
            try await api.addGoal(text: text, deadline: deadline)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("goals.errorAdd")
            return false
        }
    }

    /// تعديل نص/موعد هدف ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة.
    func update(api: APIClient, id: String, text: String, deadline: String) async -> Bool {
        do {
            try await api.updateGoal(id: id, text: text, deadline: deadline)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("goals.errorEdit")
            return false
        }
    }

    /// تبديل حالة الهدف (نشط ↔ مكتمل) تفاؤليًا، ثم مصالحة مع الباك-إند عند الفشل.
    func toggleDone(api: APIClient, goal: GoalItem) {
        guard let idx = goals.firstIndex(where: { $0.id == goal.id }) else { return }
        let newStatus = goal.isDone ? "active" : "done"
        optimistic(
            "goals.errorEdit",
            apply: {
                self.goals[idx] = GoalItem(id: goal.id, text: goal.text,
                                           deadline: goal.deadline, status: newStatus)
            },
            rollback: {
                if let i = self.goals.firstIndex(where: { $0.id == goal.id }) { self.goals[i] = goal }
            },
            call: { try await api.updateGoal(id: goal.id, status: newStatus) }
        )
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, goal: GoalItem) {
        guard let idx = goals.firstIndex(where: { $0.id == goal.id }) else { return }
        optimistic(
            "goals.errorDelete",
            apply: { self.goals.remove(at: idx) },
            rollback: { self.goals.insert(goal, at: min(idx, self.goals.count)) },
            call: { try await api.deleteGoal(id: goal.id) }
        )
    }
}
