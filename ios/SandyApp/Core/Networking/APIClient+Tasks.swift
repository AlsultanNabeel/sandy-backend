import Foundation

// The Tasks screen (`api/tasks_api.py`, behind the `tasks` switch): the tasks Sandy runs on
// her own, what each one found, and the email the results go to.

/// The server's ISO time (microseconds and all) as a date.
private func serverDate(_ iso: String) -> Date? {
    let plain = iso.replacingOccurrences(of: #"\.\d+"#, with: "", options: .regularExpression)
    return ISO8601DateFormatter().date(from: plain)
}

struct ScheduledTask: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let instructions: String
    let everyMinutes: Int
    var status: String
    let nextAt: String
    let failures: Int
    let lastError: String
    let lastResult: String
    var unseen: Int
    /// How its results are emailed; nil from a server before it was asked.
    var delivery: TaskDelivery?
    /// What its results and emails are in («ar», «en»): the language it was asked in.
    var lang: String?

    var paused: Bool { status == "paused" }
    var nextDate: Date? { serverDate(nextAt) }
    var way: TaskDelivery { delivery ?? .hourly }

    enum CodingKeys: String, CodingKey {
        case id, title, instructions, status, failures, unseen, delivery, lang
        case everyMinutes = "every_minutes", nextAt = "next_at"
        case lastError = "last_error", lastResult = "last_result"
    }
}

/// How a task's results are emailed (`blocks/tasks.py` delivery): right away, a summary once
/// a day at `at` («HH:MM» on his clock), or at most once every `hours`.
struct TaskDelivery: Codable, Hashable {
    var mode: String
    var hours: Int?
    var at: String?

    static let instant = "instant", daily = "daily", every = "every"
    static let hourly = TaskDelivery(mode: every, hours: 1)
}

/// The check new words bring (from the preview), handed back with the change so what was
/// shown is what is saved.
struct TaskCheck: Codable, Hashable {
    let tool: String
    let args: [String: JSONValue]
}

/// A change from the screen; what is nil stays as it is.
struct TaskChange: Encodable, Equatable {
    var everyMinutes: Int?
    var delivery: TaskDelivery?
    var instructions: String?
    var check: TaskCheck?
    var lang: String?

    var isEmpty: Bool { everyMinutes == nil && delivery == nil && instructions == nil && lang == nil }

    enum CodingKeys: String, CodingKey {
        case delivery, instructions, check, lang
        case everyMinutes = "every_minutes"
    }
}

/// The question a change waits on, the same as Sandy asks by talk, and the check new words
/// bring.
struct TaskPreview: Decodable {
    let summary: String
    let check: TaskCheck?
}

struct ScheduledTaskResult: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let body: String
    let at: String
    let seen: Bool

    var date: Date? { serverDate(at) }
}

/// Where results are emailed: `ready` is false until the server's mail settings are in.
struct NotifyEmail: Decodable, Equatable {
    let address: String
    let confirmed: Bool
    let ready: Bool
}

private struct ScheduledTasksResponse: Decodable { let tasks: [ScheduledTask] }
private struct ScheduledTaskResponse: Decodable { let task: ScheduledTask }
private struct ScheduledTaskResultsResponse: Decodable { let results: [ScheduledTaskResult] }
private struct NotifyEmailAsked: Decodable { let state: String }
private struct NotifyEmailBody: Encodable { let address: String }

extension APIClient {
    func scheduledTasks() async throws -> [ScheduledTask] {
        let r: ScheduledTasksResponse = try await fetch("/api/scheduled-tasks")
        return r.tasks
    }

    func scheduledTaskResults(id: String) async throws -> [ScheduledTaskResult] {
        let r: ScheduledTaskResultsResponse =
            try await fetch("/api/scheduled-tasks/\(URLEscape.segment(id))/results")
        return r.results
    }

    func markScheduledTaskSeen(id: String) async throws {
        try await send("/api/scheduled-tasks/\(URLEscape.segment(id))/seen", method: "POST")
    }

    func pauseScheduledTask(id: String) async throws {
        try await send("/api/scheduled-tasks/\(URLEscape.segment(id))/pause", method: "POST")
    }

    func resumeScheduledTask(id: String) async throws {
        try await send("/api/scheduled-tasks/\(URLEscape.segment(id))/resume", method: "POST")
    }

    func removeScheduledTask(id: String) async throws {
        try await send("/api/scheduled-tasks/\(URLEscape.segment(id))", method: "DELETE")
    }

    /// What the change would be, asked before it is saved; nothing is saved.
    func previewScheduledTask(id: String, change: TaskChange) async throws -> TaskPreview {
        try await fetch("/api/scheduled-tasks/\(URLEscape.segment(id))/preview", method: "POST",
                        body: change)
    }

    /// The change saved; the task as it is now.
    func changeScheduledTask(id: String, change: TaskChange) async throws -> ScheduledTask {
        let r: ScheduledTaskResponse = try await fetch("/api/scheduled-tasks/\(URLEscape.segment(id))",
                                                       method: "PATCH", body: change)
        return r.task
    }

    func notifyEmail() async throws -> NotifyEmail {
        try await fetch("/api/notify/email")
    }

    /// Sends the confirmation link: "sent", "pending" (one just went) or "confirmed".
    func setNotifyEmail(_ address: String) async throws -> String {
        let r: NotifyEmailAsked = try await fetch("/api/notify/email", method: "POST",
                                                  body: NotifyEmailBody(address: address))
        return r.state
    }

    func forgetNotifyEmail() async throws {
        try await send("/api/notify/email", method: "DELETE")
    }
}
