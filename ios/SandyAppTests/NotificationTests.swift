import UserNotifications
import XCTest
@testable import SandyApp

/// A notification center that only records: what is pending, by id, answered at once.
final class FakeScheduler: NotificationScheduler {
    weak var delegate: UNUserNotificationCenterDelegate?
    var pending: [String: UNNotificationRequest] = [:]
    var allowed = true

    func add(_ request: UNNotificationRequest, withCompletionHandler completionHandler: ((Error?) -> Void)?) {
        pending[request.identifier] = request
        completionHandler?(nil)
    }
    func getPendingNotificationRequests(completionHandler: @escaping ([UNNotificationRequest]) -> Void) {
        completionHandler(Array(pending.values))
    }
    func removePendingNotificationRequests(withIdentifiers identifiers: [String]) {
        for id in identifiers { pending[id] = nil }
    }
    func removeDeliveredNotifications(withIdentifiers identifiers: [String]) {}
    func removeAllPendingNotificationRequests() { pending = [:] }
    func removeAllDeliveredNotifications() {}
    func setNotificationCategories(_ categories: Set<UNNotificationCategory>) {}
    func notificationsAllowed(_ done: @escaping (Bool) -> Void) { done(allowed) }

    func ids(_ prefix: String) -> [String] { pending.keys.filter { $0.hasPrefix(prefix) }.sorted() }
}

/// Audit batch nine: notifications on the phone.
@MainActor
final class NotificationTests: XCTestCase {
    private var fake: FakeScheduler!
    private var original: NotificationScheduler!
    private var savedPrefs: Data?
    private let notes = NotificationManager.shared

    override func setUp() async throws {
        try await super.setUp()
        savedPrefs = UserDefaults.standard.data(forKey: "notifications.prefs")
        NotificationPrefs().save()
        original = notes.center
        fake = FakeScheduler()
        notes.center = fake
        notes.sessionBegan()
    }

    override func tearDown() async throws {
        notes.clearForSignOut()
        notes.center = original
        if let savedPrefs { UserDefaults.standard.set(savedPrefs, forKey: "notifications.prefs") }
        else { UserDefaults.standard.removeObject(forKey: "notifications.prefs") }
        StubNetwork.uninstall()
        try await super.tearDown()
    }
}
