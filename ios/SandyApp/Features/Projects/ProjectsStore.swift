import SwiftUI

@MainActor
final class ProjectsStore: LoadableStore {
    @Published var plans: [ProjectPlan] = []
    @Published var active: ActiveBrainstorm?
    @Published var finishing = false

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                async let plansCall = api.getPlans()
                async let activeCall = api.getActiveBrainstorm()
                plans = try await plansCall
                active = try await activeCall
            } catch {
                if !error.isCancellation { notify("projects.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    func start(api: APIClient, topic: String) async -> Bool {
        do {
            active = try await api.startBrainstorm(topic: topic)
            clearNotice()
            return true
        } catch {
            notify("projects.errorStart")
            return false
        }
    }

    /// إضافة متفائلة فوراً على الجلسة المحلية، ثم تُرسل للباك-إند.
    func addPoint(api: APIClient, point: String) {
        active?.points.append(point)
        Task { @MainActor in
            do {
                try await api.addBrainstormPoint(point)
            } catch {
                if let idx = active?.points.lastIndex(of: point) { active?.points.remove(at: idx) }
                notify("projects.errorAdd")
            }
        }
    }

    func finish(api: APIClient) {
        guard !finishing else { return }
        finishing = true
        Task { @MainActor in
            defer { finishing = false }
            do {
                _ = try await api.finishBrainstorm()
                active = nil
                clearNotice()
                await load(api: api)
            } catch {
                notify("projects.errorFinish")
            }
        }
    }

    func cancel(api: APIClient) {
        let previous = active
        active = nil
        Task { @MainActor in
            do {
                try await api.cancelBrainstorm()
            } catch {
                active = previous
                notify("projects.errorCancel")
            }
        }
    }

    /// يرجع نجاح/فشل لتقرّر لوحة التعديل تتقفل. يحدّث نص الخطة محلياً عند النجاح.
    func update(api: APIClient, id: String, change: String) async -> Bool {
        do {
            let revised = try await api.updatePlan(id: id, change: change)
            if let idx = plans.firstIndex(where: { $0.id == id }) {
                plans[idx].planText = revised
            }
            clearNotice()
            return true
        } catch {
            notify("projects.errorUpdate")
            return false
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, plan: ProjectPlan) {
        guard let idx = plans.firstIndex(where: { $0.id == plan.id }) else { return }
        optimistic(
            "projects.errorDelete",
            apply: { self.plans.remove(at: idx) },
            rollback: { self.plans.insert(plan, at: min(idx, self.plans.count)) },
            call: { try await api.deletePlan(id: plan.id) }
        )
    }
}
