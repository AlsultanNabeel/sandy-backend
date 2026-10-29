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

    var paused: Bool { status == "paused" }
    var nextDate: Date? { serverDate(nextAt) }

    enum CodingKeys: String, CodingKey {
        case id, title, instructions, status, failures, unseen
        case everyMinutes = "every_minutes", nextAt = "next_at"
        case lastError = "last_error", lastResult = "last_result"
    }
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
