import Foundation

extension APIClient {
    func notificationSettings() async throws -> NotificationPrefs {
        try await fetch("/api/notification-settings")
    }

    func saveNotificationSettings(_ prefs: NotificationPrefs) async throws {
        try await send("/api/notification-settings", method: "POST", body: prefs)
    }

    private struct Feedback: Encodable {
        let text: String
        let version: String
        let device: String
        let os: String
    }

    func sendFeedback(text: String, version: String, device: String, system: String) async throws {
        try await send("/api/feedback", method: "POST",
                       body: Feedback(text: text, version: version, device: device, os: system))
    }
}
