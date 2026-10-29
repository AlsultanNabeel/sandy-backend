import XCTest
@testable import SandyApp

/// Phase one: the Tasks screen behind the `tasks` switch: the tasks and their state, each
/// one's results, pause, resume and remove, and the email the results go to.
@MainActor
final class ScheduledTasksTests: XCTestCase {
    override func tearDown() {
        StubNetwork.uninstall()
        super.tearDown()
    }

    private func paths() -> [String] {
        StubNetwork.requests.map { "\($0.httpMethod ?? "") \($0.url?.path ?? "")" }
    }

    func testTheScreenShowsOnlyWithTheSwitch() {
        XCTAssertTrue(ScheduledTasksAccess.shows(on: ["tasks"]))
        XCTAssertFalse(ScheduledTasksAccess.shows(on: ["dev_tools"]))
    }

    func testTheTasksAreRead() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: """
        {"tasks": [{"id": "t1", "title": "الدهب", "instructions": "شوفي سعر الدهب",
          "every_minutes": 60, "status": "paused", "next_at": "2026-10-29T10:00:00+00:00",
          "failures": 1, "last_error": "RuntimeError: down", "last_result": "طلع ٢٪",
          "unseen": 2}]}
        """)
        let rows = try await api.scheduledTasks()
        XCTAssertEqual(rows.map(\.id), ["t1"])
        XCTAssertEqual(rows[0].title, "الدهب")
        XCTAssertEqual(rows[0].everyMinutes, 60)
        XCTAssertTrue(rows[0].paused)
        XCTAssertEqual(rows[0].unseen, 2)
        XCTAssertEqual(rows[0].failures, 1)
        XCTAssertEqual(paths(), ["GET /api/scheduled-tasks"])
    }

    func testATasksResultsAreReadAndSeen() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: """
        {"results": [{"id": "r2", "title": "Gold", "body": "down 1%",
          "at": "2026-10-29T09:00:00+00:00", "seen": false}]}
        """)
        let rows = try await api.scheduledTaskResults(id: "t1")
        XCTAssertEqual(rows.map(\.body), ["down 1%"])
        XCTAssertNotNil(rows[0].date)
        StubNetwork.install(json: #"{"ok": true}"#)
        try await api.markScheduledTaskSeen(id: "t1")
        XCTAssertEqual(paths(), ["POST /api/scheduled-tasks/t1/seen"])
    }

    func testPauseResumeAndRemoveGoToTheirRoutes() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: #"{"ok": true}"#)
        try await api.pauseScheduledTask(id: "t1")
        try await api.resumeScheduledTask(id: "t1")
        try await api.removeScheduledTask(id: "t1")
        XCTAssertEqual(paths(), ["POST /api/scheduled-tasks/t1/pause",
                                 "POST /api/scheduled-tasks/t1/resume",
                                 "DELETE /api/scheduled-tasks/t1"])
    }

    func testTheStorePausesAndShowsItAtOnce() async {
        let api = TestClient.make()
        let store = ScheduledTasksStore()
        store.tasks = [ScheduledTask(id: "t1", title: "Gold", instructions: "", everyMinutes: 60,
                                     status: "running", nextAt: "", failures: 0, lastError: "",
                                     lastResult: "", unseen: 0, delivery: nil)]
        StubNetwork.install(json: #"{"ok": true}"#)
        await store.setPaused(true, id: "t1", api: api)
        XCTAssertTrue(store.tasks[0].paused)
        StubNetwork.install(status: 500, json: #"{"error": "x"}"#)
        await store.setPaused(false, id: "t1", api: api)
        XCTAssertTrue(store.tasks[0].paused, "a resume that failed was shown as done")
        XCTAssertFalse(store.notice.isEmpty)
    }

    /// A change made elsewhere (chat, a call, the robot) shows here: the quiet refresh takes the
    /// server's tasks as they are now, and a failed one leaves the screen as it was.
    func testAQuietRefreshShowsAChangeMadeElsewhere() async {
        let api = TestClient.make()
        let store = ScheduledTasksStore()
        store.tasks = [ScheduledTask(id: "t1", title: "Gold", instructions: "", everyMinutes: 60,
                                     status: "running", nextAt: "", failures: 0, lastError: "",
                                     lastResult: "", unseen: 0, delivery: nil)]
        StubNetwork.install(json: """
        {"tasks": [{"id": "t1", "title": "Gold", "instructions": "", "every_minutes": 120,
          "status": "paused", "next_at": "", "failures": 0, "last_error": "", "last_result": "",
          "unseen": 1}]}
        """)
        await store.refresh(api: api)
        XCTAssertTrue(store.tasks[0].paused)
        XCTAssertEqual(store.tasks[0].everyMinutes, 120)
        StubNetwork.install(status: 500, json: #"{"error": "x"}"#)
        await store.refresh(api: api)
        XCTAssertEqual(store.tasks.count, 1)
        XCTAssertTrue(store.notice.isEmpty, "a quiet refresh never shows a notice")
    }

    private func gold(_ way: TaskDelivery? = nil) -> ScheduledTask {
        ScheduledTask(id: "t1", title: "Gold", instructions: "check gold", everyMinutes: 60,
                      status: "running", nextAt: "", failures: 0, lastError: "", lastResult: "",
                      unseen: 0, delivery: way)
    }

    /// The screen changes what talk changes: only what differs is sent, and the way of telling
    /// is read as the server keeps it (an old row with none is once an hour).
    func testOnlyWhatChangedIsSent() {
        let task = gold()
        XCTAssertTrue(TaskEditSheet.change(from: task, words: "check gold ", minutes: 60,
                                           way: .hourly).isEmpty)
        let c = TaskEditSheet.change(from: task, words: "check silver", minutes: 120,
                                     way: TaskDelivery(mode: TaskDelivery.daily, at: "21:00"))
        XCTAssertEqual(c.instructions, "check silver")
        XCTAssertEqual(c.everyMinutes, 120)
        XCTAssertEqual(c.delivery, TaskDelivery(mode: TaskDelivery.daily, at: "21:00"))
    }

    /// A change is previewed (the question by talk), then saved with the check the preview
    /// brought, and the screen shows the task as the server keeps it.
    func testAChangeIsPreviewedThenSavedWithItsCheck() async throws {
        let api = TestClient.make()
        let store = ScheduledTasksStore()
        store.tasks = [gold()]
        StubNetwork.install(json: """
        {"summary": "make «Gold» every 2 hours: «check silver», telling you right away",
         "check": {"tool": "web_search", "args": {"query": "silver price"}}}
        """)
        var change = TaskChange(everyMinutes: 120, delivery: TaskDelivery(mode: TaskDelivery.instant),
                                instructions: "check silver")
        let preview = await store.preview(change, id: "t1", api: api)
        XCTAssertEqual(paths(), ["POST /api/scheduled-tasks/t1/preview"])
        XCTAssertEqual(preview?.check?.tool, "web_search")
        XCTAssertEqual(store.tasks[0].instructions, "check gold", "a preview saved nothing")
        change.check = preview?.check
        StubNetwork.install(json: """
        {"task": {"id": "t1", "title": "Gold", "instructions": "check silver", "every_minutes": 120,
          "status": "running", "next_at": "", "failures": 0, "last_error": "", "last_result": "",
          "unseen": 0, "delivery": {"mode": "instant"}}}
        """)
        let saved = await store.save(change, id: "t1", api: api)
        XCTAssertTrue(saved)
        XCTAssertEqual(store.tasks[0].instructions, "check silver")
        XCTAssertEqual(store.tasks[0].way, TaskDelivery(mode: TaskDelivery.instant))
        let sent = try XCTUnwrap(StubNetwork.requests.last?.httpBody)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: sent) as? [String: Any])
        XCTAssertEqual((body["check"] as? [String: Any])?["tool"] as? String, "web_search")
        XCTAssertEqual(paths(), ["PATCH /api/scheduled-tasks/t1"])
    }

    /// A change the server cannot read is said in its own words, and nothing changes here.
    func testARefusedChangeSaysWhy() async {
        let api = TestClient.make()
        let store = ScheduledTasksStore()
        store.tasks = [gold()]
        StubNetwork.install(status: 400, json: #"{"error": "bad_delivery", "message": "needs its hour"}"#)
        let ok = await store.save(TaskChange(delivery: TaskDelivery(mode: TaskDelivery.daily)), id: "t1", api: api)
        XCTAssertFalse(ok)
        XCTAssertEqual(store.notice, "needs its hour")
        XCTAssertEqual(store.tasks[0].way, .hourly)
    }

    func testTheStoreRemovesATask() async {
        let api = TestClient.make()
        let store = ScheduledTasksStore()
        store.tasks = [ScheduledTask(id: "t1", title: "Gold", instructions: "", everyMinutes: 60,
                                     status: "running", nextAt: "", failures: 0, lastError: "",
                                     lastResult: "", unseen: 0, delivery: nil)]
        StubNetwork.install(json: #"{"ok": true}"#)
        await store.remove(id: "t1", api: api)
        XCTAssertTrue(store.tasks.isEmpty)
    }

    func testTheEmailIsReadAndALinkAsked() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: #"{"address": "me@example.com", "confirmed": false, "ready": true}"#)
        let mail = try await api.notifyEmail()
        XCTAssertEqual(mail.address, "me@example.com")
        XCTAssertFalse(mail.confirmed)
        XCTAssertTrue(mail.ready)
        StubNetwork.install(json: #"{"ok": true, "state": "sent"}"#)
        let state = try await api.setNotifyEmail("me@example.com")
        XCTAssertEqual(state, "sent")
        let body = try JSONSerialization.jsonObject(
            with: StubNetwork.body(of: StubNetwork.requests[0])) as? [String: String]
        XCTAssertEqual(body, ["address": "me@example.com"])
        StubNetwork.install(json: #"{"ok": true}"#)
        try await api.forgetNotifyEmail()
        XCTAssertEqual(paths(), ["DELETE /api/notify/email"])
    }

    func testEveryStringIsInBothLanguages() {
        let table = L10nTasks.table
        XCTAssertEqual(Set(table.ar.keys), Set(table.en.keys))
    }
}
