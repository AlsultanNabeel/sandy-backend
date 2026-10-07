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
        notes.client = { [unowned self] in self.api }
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
        Outbox.shared.discard()
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

    /// F29: «every day from next Monday» had a daily trigger, which rang from tomorrow. The
    /// first time is one ring, told to the server as that ring only, so it pushes the rest.
    func testARepeatStartingLaterRingsFirstOnItsDayAndIsArmedForThatRingOnly() async throws {
        notes.handleDeviceToken(Data([0xab, 0xcd]))
        notes.sync(prefix: "reminder.", items: [reminder("later", in: 3 * 86_400, repeats: .daily),
                                                reminder("soon", in: 3600, repeats: .daily)])
        let later = try XCTUnwrap(fake.pending["reminder.later"]?.trigger as? UNCalendarNotificationTrigger)
        XCTAssertFalse(later.repeats, "the repeat rings before its first day")
        let first = try XCTUnwrap(later.nextTriggerDate())
        XCTAssertEqual(first.timeIntervalSinceNow, 3 * 86_400, accuracy: 120)
        let soon = try XCTUnwrap(fake.pending["reminder.soon"]?.trigger as? UNCalendarNotificationTrigger)
        XCTAssertTrue(soon.repeats)
        await waitFor { !sent("/api/schedules/armed").isEmpty }
        let body = try XCTUnwrap(sent("/api/schedules/armed").last)
        XCTAssertEqual((body["ids"] as? [String])?.sorted(), ["later", "soon"])
        XCTAssertEqual(body["once"] as? [String], ["later"])
    }

    private static func row(_ id: String, recurrence: String, in seconds: TimeInterval = -60) -> ScheduleItem {
        ScheduleItem(id: id, kind: "reminder", text: "الدوا",
                     fireAt: ISO8601DateFormatter().string(from: Date().addingTimeInterval(seconds)),
                     recurrence: recurrence, status: "pending")
    }

    /// A reminders store holding `rows`, as loaded from the server.
    private func loaded(_ rows: [ScheduleItem]) async throws -> SchedulesStore {
        let json = String(decoding: try JSONEncoder().encode(rows), as: UTF8.self)
        StubNetwork.install { req in
            req.httpMethod == "GET" ? (200, Data("{\"items\":\(json)}".utf8)) : (200, Data("{}".utf8))
        }
        let store = SchedulesStore()
        await store.load(api: api)
        return store
    }

    /// F23: «later» in the app sent a new time only: a repeat moved its whole series
    /// («every day at 8» became 8:15 for good). It goes through the snooze route now, and a
    /// repeat rings a one-time copy under the phone's own id.
    func testLaterOnARepeatRingsACopyAndLeavesTheSeries() async throws {
        let series = Self.row("s1", recurrence: "FREQ=DAILY")
        let store = try await loaded([series])
        store.snooze(api: api, series, minutes: 15)
        await waitFor { !sent("/api/schedules/s1/snooze").isEmpty }
        let body = try XCTUnwrap(sent("/api/schedules/s1/snooze").first)
        XCTAssertEqual(body["minutes"] as? Int, 15)
        let copyId = try XCTUnwrap(body["id"] as? String)
        XCTAssertEqual(store.items.first { $0.id == "s1" }?.fireAt, series.fireAt, "the series moved")
        let copy = try XCTUnwrap(store.items.first { $0.id == copyId })
        XCTAssertEqual(copy.recurrence, "")
        XCTAssertTrue(StubNetwork.requests.allSatisfy { $0.httpMethod != "PATCH" })
    }

    /// F23: a one-off that rang goes back to pending at the new time, with no copy.
    func testLaterOnAOneOffMovesIt() async throws {
        let once = Self.row("o1", recurrence: "")
        let store = try await loaded([once])
        store.snooze(api: api, once, minutes: 60)
        await waitFor { !sent("/api/schedules/o1/snooze").isEmpty }
        XCTAssertNil(sent("/api/schedules/o1/snooze").first?["id"])
        XCTAssertEqual(store.items.map(\.id), ["o1"])
        let at = try XCTUnwrap(NotificationManager.parseISO(store.items[0].fireAt))
        XCTAssertEqual(at.timeIntervalSinceNow, 3600, accuracy: 5)
    }

    /// F23: «later» on a repeat's banner dropped its repeating notification until the next
    /// sync and rang the snooze on the series' id; the series keeps ringing, the copy rings
    /// under its own id.
    func testLaterFromTheBannerOfARepeatKeepsItsRepeatAndRingsTheCopy() async throws {
        notes.sync(prefix: "reminder.", items: [reminder("s1", in: 3600, repeats: .daily)])
        let content = UNMutableNotificationContent()
        content.body = "الدوا"
        content.userInfo = [NotificationManager.reminderIdKey: "s1",
                            NotificationManager.reminderRecurrenceKey: "FREQ=DAILY"]
        let request = UNNotificationRequest(identifier: "reminder.s1", content: content, trigger: nil)
        let done = expectation(description: "answered")
        notes.perform(.snooze, reminderId: "s1", notification: request) { done.fulfill() }
        await fulfillment(of: [done], timeout: 5)
        XCTAssertNotNil(fake.pending["reminder.s1"], "the series' repeat was dropped")
        let copyId = try XCTUnwrap(sent("/api/schedules/s1/snooze").first?["id"] as? String)
        let copy = try XCTUnwrap(fake.pending["reminder." + copyId])
        XCTAssertEqual(copy.content.userInfo[NotificationManager.reminderIdKey] as? String, copyId)
        XCTAssertEqual(copy.content.userInfo[NotificationManager.reminderRecurrenceKey] as? String, "")
    }

    /// S3: «later» waited for the server before scheduling the new ring; on a weak network
    /// the app was suspended first and the reminder never rang again.
    func testLaterFromTheBannerRingsBeforeTheServerAnswers() async throws {
        StubNetwork.delay("POST", by: 3)
        let content = UNMutableNotificationContent()
        content.body = "المي"
        content.userInfo = [NotificationManager.reminderIdKey: "o1", NotificationManager.reminderRecurrenceKey: ""]
        let request = UNNotificationRequest(identifier: "reminder.o1", content: content, trigger: nil)
        notes.perform(.snooze, reminderId: "o1", notification: request) {}
        await waitFor { fake.pending["reminder.o1"] != nil }
        XCTAssertNotNil(fake.pending["reminder.o1"], "the new ring waited for the server (answering in three seconds)")
    }

    /// E1: a reminder added from Siri or Shortcuts went to the server only, so the phone
    /// never rang it; it is scheduled under the id the server keeps.
    func testAReminderFromSiriRingsOnThePhone() async throws {
        try await AddReminderIntent.add(api: api, text: "اتصل بأمي", at: Date().addingTimeInterval(7200))
        let id = try XCTUnwrap(sent("/api/schedules").first?["id"] as? String)
        let note = try XCTUnwrap(fake.pending["reminder." + id], "the reminder was not scheduled")
        XCTAssertEqual(note.content.body, "اتصل بأمي")
        XCTAssertEqual(note.content.categoryIdentifier, NotificationManager.reminderCategory)
    }

    /// F24: a reminder made on the robot or in another place reached the phone only if the
    /// app was opened in time; the server's silent push now reloads and schedules it.
    func testASilentPushSchedulesTheRemindersMadeElsewhere() async throws {
        let row = Self.row("robot1", recurrence: "", in: 3600)
        let json = String(decoding: try JSONEncoder().encode([row]), as: UTF8.self)
        StubNetwork.install { req in
            req.httpMethod == "GET" ? (200, Data("{\"items\":\(json)}".utf8)) : (200, Data("{}".utf8))
        }
        let done = expectation(description: "fetched")
        var result: UIBackgroundFetchResult?
        AppDelegate().application(UIApplication.shared, didReceiveRemoteNotification: ["sync": "schedules"]) {
            result = $0
            done.fulfill()
        }
        await fulfillment(of: [done], timeout: 5)
        XCTAssertEqual(result, .newData)
        XCTAssertNotNil(fake.pending["reminder.robot1"], "the robot's reminder was not scheduled")
    }

    /// F24: a reminder made during the app's call did not reach the screens (or the
    /// notifications) until the next reload; the call's end says the blocks changed.
    func testTheEndOfACallSaysTheBlocksChanged() async {
        let changed = expectation(forNotification: .sandyBlocksChanged, object: nil)
        let call = GeminiLiveManager.shared
        call.phase = .listening
        call.stop()
        await fulfillment(of: [changed], timeout: 2)
    }

    /// E3: the widget had one entry, renewed hourly, so «next reminder at nine» stayed up
    /// until three; it shows each until its time, then the next.
    func testTheWidgetShowsEachReminderUntilItsTimeThenTheNext() {
        let now = Date()
        let a = UpcomingReminders.Ring(text: "a", at: now.addingTimeInterval(3600))
        let b = UpcomingReminders.Ring(text: "b", at: now.addingTimeInterval(7200))
        let old = UpcomingReminders.Ring(text: "old", at: now.addingTimeInterval(-60))
        let line = UpcomingReminders(rings: [b, old, a]).timeline(from: now)
        XCTAssertEqual(line.map(\.ring?.text), ["a", "b", nil])
        XCTAssertEqual(line.map(\.date), [now, a.at, b.at])
    }

    /// E3: the app writes each reminder's next ring, a repeat's too (not its past time).
    func testTheAppWritesTheNextRingOfEachReminder() throws {
        let yesterday = Date().addingTimeInterval(-86_400)
        let rows = [Self.row("d", recurrence: "FREQ=DAILY", in: -86_400),
                    Self.row("o", recurrence: "", in: 1800),
                    Self.row("gone", recurrence: "", in: -60)]
        let up = SchedulesStore.upcoming(rows)
        XCTAssertEqual(Set(up.rings.map(\.text)).count, 1)  // all rows share a text
        XCTAssertEqual(up.rings.count, 2)
        XCTAssertTrue(up.rings.allSatisfy { $0.at > Date() && $0.at > yesterday })
        XCTAssertEqual(up.rings, up.rings.sorted { $0.at < $1.at })
    }

    /// E5: ✓ on the tasks widget did not take the task's notification away, so it rang (an
    /// alarm, for an important one) on a task already done; the ✓ runs in the app now.
    func testATaskDoneFromTheWidgetDoesNotRing() async throws {
        notes.sync(prefix: "task.", items: [reminder("t1", in: 3600, alarm: true), reminder("t2", in: 7200)])
        XCTAssertNotNil(fake.pending["task.t1"])
        try await CompleteTaskIntent.complete("t1", api: api)
        XCTAssertTrue(fake.ids("task.t1").isEmpty, "the done task still rings")
        XCTAssertNotNil(fake.pending["task.t2"])
        let patch = try XCTUnwrap(sent("/api/items/t1").first)
        XCTAssertEqual(patch["done"] as? Bool, true)
    }
}
