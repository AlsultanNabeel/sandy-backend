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
                                     lastResult: "", unseen: 0)]
        StubNetwork.install(json: #"{"ok": true}"#)
        await store.setPaused(true, id: "t1", api: api)
        XCTAssertTrue(store.tasks[0].paused)
        StubNetwork.install(status: 500, json: #"{"error": "x"}"#)
        await store.setPaused(false, id: "t1", api: api)
        XCTAssertTrue(store.tasks[0].paused, "a resume that failed was shown as done")
        XCTAssertFalse(store.notice.isEmpty)
    }

    func testTheStoreRemovesATask() async {
        let api = TestClient.make()
        let store = ScheduledTasksStore()
        store.tasks = [ScheduledTask(id: "t1", title: "Gold", instructions: "", everyMinutes: 60,
                                     status: "running", nextAt: "", failures: 0, lastError: "",
                                     lastResult: "", unseen: 0)]
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
