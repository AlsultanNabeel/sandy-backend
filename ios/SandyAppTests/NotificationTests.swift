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
        NotificationManager.armDelay = 0
        api = TestClient.make()
        api.token = SessionTests.token("notes-\(UUID().uuidString.prefix(8))")
        notes.armingAPI = { [unowned self] in self.api }
        StubNetwork.install(json: "{}")
    }

    private var api: APIClient!

    /// The bodies of what went to `path`, in order.
    private func sent(_ path: String) -> [[String: Any]] {
        StubNetwork.requests.filter { $0.url?.path == path }.compactMap {
            try? JSONSerialization.jsonObject(with: StubNetwork.body(of: $0)) as? [String: Any]
        }
    }

    private func waitFor(_ check: () -> Bool) async {
        for _ in 0..<100 where !check() { try? await Task.sleep(nanoseconds: 20_000_000) }
    }

    private func reminder(_ id: String, in seconds: TimeInterval, repeats: NotificationRepeat = .none,
                          alarm: Bool = false) -> NotificationItem {
        NotificationItem(id: id, title: "تذكير", body: id, date: Date().addingTimeInterval(seconds),
                         repeats: repeats, alarm: alarm)
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

    /// S8: the phone tells the server every reminder it scheduled (the whole set), so the
    /// server's push goes only to what the phone does not ring; tasks are not reminders.
    func testThePhoneTellsTheServerWhichRemindersItScheduled() async throws {
        notes.handleDeviceToken(Data([0xab, 0xcd]))
        notes.sync(prefix: "task.", items: [reminder("t1", in: 3600)])
        notes.sync(prefix: "reminder.", items: [reminder("b", in: 7200), reminder("a", in: 3600)])
        await waitFor { !sent("/api/schedules/armed").isEmpty }
        let body = try XCTUnwrap(sent("/api/schedules/armed").last)
        XCTAssertEqual(body["token"] as? String, "abcd")
        XCTAssertEqual((body["ids"] as? [String])?.sorted(), ["a", "b"])
    }

    /// S8: a reminder pushed by the server opened Today, not the reminders.
    func testAReminderPushOpensTheReminders() {
        XCTAssertEqual(NotificationManager.route(kind: "reminder", identifier: "x"), .reminders)
        XCTAssertEqual(NotificationManager.route(kind: "daily_nudge", identifier: "x"), .dailyNudge)
        XCTAssertEqual(NotificationManager.route(kind: nil, identifier: "task.1"), .tasks)
    }

    /// S8: a phone leaving the account says it holds none first, so the server pushes again
    /// rather than count on a phone that left.
    func testLeavingTheAccountEmptiesTheSetBeforeTheTokenGoes() async throws {
        notes.handleDeviceToken(Data([0xab, 0xcd]))
        await notes.leave(api: api, bearer: "old-session")
        let paths = StubNetwork.requests.compactMap { $0.url?.path }
        XCTAssertEqual(paths, ["/api/schedules/armed", "/api/push/unregister"])
        XCTAssertEqual(sent("/api/schedules/armed").first?["ids"] as? [String], [])
        XCTAssertEqual(StubNetwork.requests.first?.value(forHTTPHeaderField: "Authorization"),
                       "Bearer old-session")
    }

    /// S9: an alarm takes three requests and the system keeps sixty-four, dropping the rest
    /// without a word; the nearest go under a cap, and only those are told to the server.
    func testTheNearestFitUnderTheSystemsLimitAndOnlyThoseAreArmed() async throws {
        notes.handleDeviceToken(Data([0xab, 0xcd]))
        let alarms = (0..<30).map { reminder(String(format: "r%02d", $0), in: Double($0 + 1) * 3600, alarm: true) }
        notes.sync(prefix: "reminder.", items: alarms.reversed())
        let items = fake.pending.keys.filter { !$0.hasPrefix(NotificationManager.proactivePrefix) }
        XCTAssertLessThanOrEqual(items.count, NotificationManager.itemBudget)
        XCTAssertLessThanOrEqual(fake.pending.count, 64)
        XCTAssertNotNil(fake.pending["reminder.r00"], "the nearest was left out")
        XCTAssertNil(fake.pending["reminder.r29"], "the farthest went past the cap")
        await waitFor { !sent("/api/schedules/armed").isEmpty }
        let armed = try XCTUnwrap(sent("/api/schedules/armed").last?["ids"] as? [String])
        XCTAssertEqual(Set(armed), Set(items.filter { !$0.contains(".again") }.map { String($0.dropFirst("reminder.".count)) }),
                       "a reminder not scheduled was told to the server")
    }

    /// S9: a habit kept every day took seven weekly requests instead of one daily.
    func testAnEveryDayHabitIsOneDailyRequest() {
        let days: [JSONValue] = (1...7).map { .number(Double($0)) }
        let habit = ListItem(id: "h1", list: "habits", text: "مشي", done: false,
                             data: ["days": .array(days), "time": .string("07:30")])
        let notes = ItemsStore.habitNotes([habit])
        XCTAssertEqual(notes.map(\.id), ["h1"])
        XCTAssertEqual(notes.first?.repeats, .daily)
    }
}
