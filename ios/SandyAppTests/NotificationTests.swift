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

    /// S2: a banner button pressed with the app closed launches it with no screen; the
    /// delegate was set only once a screen touched the manager, and nothing was scheduled
    /// with no session marked, so «later», «done» and «delete» were lost.
    func testALaunchWithNoScreenIsReadyForTheBannerButtons() {
        notes.clearForSignOut()
        let launch = AppDelegate()
        launch.hasSession = { true }
        _ = launch.application(UIApplication.shared, didFinishLaunchingWithOptions: nil)
        XCTAssertTrue(UNUserNotificationCenter.current().delegate === notes)
        XCTAssertNotNil(notes.nudgeInputs(), "a launch with a kept session scheduled nothing")
    }

    /// S11: the budget alert went out with «Sandy's nudges» switched off.
    func testTheBudgetAlertKeepsToSandysNudgesSwitch() {
        var prefs = NotificationPrefs()
        prefs.proactive = false
        prefs.save()
        notes.notifyNow(title: "الميزانية", body: "وصلت ٨٠٪")
        XCTAssertEqual(fake.ids("proactive.now."), [], "rang with Sandy's nudges off")
        NotificationPrefs().save()
        notes.clearForSignOut()
        notes.notifyNow(title: "الميزانية", body: "وصلت ٨٠٪")
        XCTAssertEqual(fake.ids("proactive.now."), [], "rang with no one signed in")
    }

    /// S6: a one-off reminder had a wall time with no zone, so after a flight it rang at
    /// that hour on the new clock; a repeat follows the clock on purpose.
    func testAOneOffKeepsItsMomentAcrossAZoneChangeAndARepeatFollowsTheClock() throws {
        let at = Date().addingTimeInterval(5 * 3600)
        notes.sync(prefix: "reminder.", items: [
            NotificationItem(id: "once", title: "تذكير", body: "المي", date: at),
            NotificationItem(id: "daily", title: "تذكير", body: "الدوا", date: at, repeats: .daily),
        ])
        let once = try XCTUnwrap(fake.pending["reminder.once"]?.trigger as? UNCalendarNotificationTrigger)
        let daily = try XCTUnwrap(fake.pending["reminder.daily"]?.trigger as? UNCalendarNotificationTrigger)
        XCTAssertEqual(once.dateComponents.timeZone, TimeZone.current, "a one-off floats with the clock")
        XCTAssertNil(daily.dateComponents.timeZone, "a repeat is pinned to one zone")
    }
}
