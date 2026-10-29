import SwiftUI

/// Who sees the Tasks screen: an account the server turned `tasks` on for (`SANDY_FLAGS`).
enum ScheduledTasksAccess {
    static let flag = "tasks"

    static func shows(on: Set<String>) -> Bool { on.contains(flag) }
}

/// The tasks Sandy runs on her own, one's results, and the email (`APIClient+Tasks`).
@MainActor
final class ScheduledTasksStore: LoadableStore {
    @Published var tasks: [ScheduledTask] = []
    @Published var results: [ScheduledTaskResult] = []
    @Published var email: NotifyEmail?

    func load(api: APIClient) async {
        let gen = beginLoad()
        defer { endLoad(gen) }
        clearNotice()
        do {
            async let rows = api.scheduledTasks()
            async let mail = api.notifyEmail()
            let (t, m) = try await (rows, mail)
            guard isCurrentLoad(gen) else { return }
            tasks = t
            email = m
        } catch {
            if !error.isCancellation, isCurrentLoad(gen) { notify("tasks.loadFailed") }
        }
    }

    /// The tasks again, quietly: a change made elsewhere (`TasksFollow`). No spinner, no notice;
    /// a failed try waits for the next.
    func refresh(api: APIClient) async {
        guard !loading, let rows = try? await api.scheduledTasks() else { return }
        tasks = rows
    }

    /// One task's results; opening them is seeing them.
    func open(_ id: String, api: APIClient) async {
        let gen = beginLoad()
        defer { endLoad(gen) }
        clearNotice()
        do {
            let rows = try await api.scheduledTaskResults(id: id)
            guard isCurrentLoad(gen) else { return }
            results = rows
            if rows.contains(where: { !$0.seen }) {
                try await api.markScheduledTaskSeen(id: id)
                if let i = tasks.firstIndex(where: { $0.id == id }) { tasks[i].unseen = 0 }
            }
        } catch {
            if !error.isCancellation, isCurrentLoad(gen) { notify("tasks.loadFailed") }
        }
    }

    /// Shown at once; put back when the server did not take it.
    func setPaused(_ paused: Bool, id: String, api: APIClient) async {
        guard let i = tasks.firstIndex(where: { $0.id == id }) else { return }
        let before = tasks[i].status
        tasks[i].status = paused ? "paused" : "running"
        clearNotice()
        do {
            if paused { try await api.pauseScheduledTask(id: id) }
            else { try await api.resumeScheduledTask(id: id) }
        } catch {
            if let j = tasks.firstIndex(where: { $0.id == id }) { tasks[j].status = before }
            notify("tasks.saveFailed")
        }
    }

    /// The question a change waits on; nil (with the server's own words as the notice) when it
    /// cannot be read.
    func preview(_ change: TaskChange, id: String, api: APIClient) async -> TaskPreview? {
        clearNotice()
        do {
            return try await api.previewScheduledTask(id: id, change: change)
        } catch let error as APIError {
            notice = error.message
        } catch {
            notify("tasks.saveFailed")
        }
        return nil
    }

    /// Saves what was previewed; the task as the server keeps it.
    func save(_ change: TaskChange, id: String, api: APIClient) async -> Bool {
        clearNotice()
        do {
            let saved = try await api.changeScheduledTask(id: id, change: change)
            if let i = tasks.firstIndex(where: { $0.id == id }) {
                var row = saved
                row.unseen = tasks[i].unseen
                tasks[i] = row
            }
            return true
        } catch let error as APIError {
            notice = error.message
        } catch {
            notify("tasks.saveFailed")
        }
        return false
    }

    func remove(id: String, api: APIClient) async {
        clearNotice()
        do {
            try await api.removeScheduledTask(id: id)
            tasks.removeAll { $0.id == id }
        } catch {
            notify("tasks.saveFailed")
        }
    }

    /// Asks for the link; the server's own words when it refuses (a bad address, too soon).
    func askEmail(_ address: String, api: APIClient) async -> Bool {
        clearNotice()
        do {
            let state = try await api.setNotifyEmail(address.trimmingCharacters(in: .whitespaces))
            email = try await api.notifyEmail()
            notify(state == "confirmed" ? "tasks.emailConfirmed" : "tasks.linkSent")
            return true
        } catch let error as APIError {
            notice = error.message
            return false
        } catch {
            notify("tasks.saveFailed")
            return false
        }
    }

    func forgetEmail(api: APIClient) async {
        clearNotice()
        do {
            try await api.forgetNotifyEmail()
            email = try await api.notifyEmail()
        } catch {
            notify("tasks.saveFailed")
        }
    }
}
