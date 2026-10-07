import AppIntents
import Foundation
import WidgetKit

/// The tasks widget's ✓. Declared the same in `SandyWidget/SandyTasksWidget.swift` (KEEP the
/// title and parameter identical): as a `LiveActivityIntent` found in both, the system runs it
/// here, in the app's process, so the task leaves the phone's notifications (an extension
/// cannot touch the app's) and its change goes through the outbox like any other.
struct CompleteTaskIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "Complete task"
    static let description = IntentDescription("Marks a Sandy task as done.")
    static let isDiscoverable = false

    @Parameter(title: "Task ID")
    var taskId: String

    init() {}

    init(taskId: String) {
        self.taskId = taskId
    }

    @MainActor
    func perform() async throws -> some IntentResult {
        try await Self.complete(taskId, api: APIClient(baseURL: Backend.currentURL))
        return .result()
    }

    /// Off the open lists and the widget at once, its notifications gone, then sent.
    @MainActor
    static func complete(_ id: String, api: APIClient) async throws {
        ItemsStore.doneElsewhere(id, userId: api.currentUserId)
        WidgetData.taskDone(id)
        try await api.updateItem(id: id, done: true)
    }
}
