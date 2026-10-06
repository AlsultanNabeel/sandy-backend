import XCTest
@testable import SandyApp

/// Audit batch four: the block stores keep what the user just did.
@MainActor
final class BlockStoreTests: XCTestCase {
    private var api: APIClient!

    override func setUp() async throws {
        try await super.setUp()
        api = TestClient.make()
        api.token = SessionTests.token("blocks-\(UUID().uuidString.prefix(8))")
    }

    override func tearDown() async throws {
        UndoCenter.shared.drop()
        Outbox.shared.discard()
        StubNetwork.uninstall()
        try await super.tearDown()
    }

    /// A list's GET answers `rows` after `delay`; writes answer at once.
    private func serve(_ rows: String, delay: TimeInterval = 0) {
        StubNetwork.install { req in
            guard req.httpMethod == "GET" else { return (200, Data("{}".utf8)) }
            // The rows for a list; no log entries (a habit's check-ins are fetched beside it).
            let page = req.url?.path == "/api/items" ? rows : ""
            return (200, Data("{\"items\":[\(page)]}".utf8))
        }
        if delay > 0 { StubNetwork.delay("GET", by: delay) }
    }

    private static let milk = #"{"id":"t1","list":"tasks","text":"حليب","done":false}"#

    /// L2: a change made while a reload was on its way was wiped by the older rows.
    func testAChangeMadeDuringAReloadIsKept() async throws {
        serve("", delay: 0.4)
        let store = ItemsStore(list: "tasks")
        let loading = Task { await store.load(api: api) }
        try await Task.sleep(nanoseconds: 100_000_000)
        await store.add(api: api, text: "خبز")
        await loading.value
        XCTAssertEqual(store.items.map(\.text), ["خبز"], "the reload wiped a row added while it was on its way")
    }

    /// L2: a change in another store does not throw this store's reload away.
    func testAnotherStoresChangeDoesNotDropThisReload() async throws {
        serve(Self.milk, delay: 0.4)
        let store = ItemsStore(list: "tasks")
        let other = ItemsStore(list: "shopping")
        let loading = Task { await store.load(api: api) }
        try await Task.sleep(nanoseconds: 100_000_000)
        await other.add(api: api, text: "خبز")
        await loading.value
        XCTAssertEqual(store.items.map(\.id), ["t1"], "another list's change dropped this one's reload")
    }

    /// L2: a row deleted with «تراجع» still offered came back with the next reload.
    func testARowDeletedWithUndoOfferedStaysGoneOnReload() async throws {
        serve(Self.milk)
        let store = ItemsStore(list: "tasks")
        await store.load(api: api)
        let milk = try XCTUnwrap(store.items.first)
        store.delete(api: api, milk)
        XCTAssertNotNil(UndoCenter.shared.offer)
        await store.load(api: api)
        XCTAssertTrue(store.items.isEmpty, "the reload brought back a row deleted moments ago")
        UndoCenter.shared.undo()
        XCTAssertEqual(store.items.map(\.id), ["t1"], "«تراجع» did not bring it back")
    }

    private static let walk = #"{"id":"h1","list":"habits","text":"مشي","done":false}"#

    /// A habits store showing `h1` ticked on `day`, as an app left open overnight holds it.
    private func habitsTicked(on day: String) async throws -> ItemsStore {
        serve(Self.walk)
        let store = ItemsStore(list: "habits")
        await store.load(api: api)
        store.checksDay = day
        store.checkedToday = ["h1": "yesterday-entry"]
        return store
    }

    /// L1: ticked before midnight, the ring was still ticked in the morning, and tapping it
    /// deleted yesterday's check-in and broke the streak.
    func testTappingYesterdaysTickChecksInTodayInstead() async throws {
        let store = try await habitsTicked(on: "2000-01-01")
        let habit = try XCTUnwrap(store.items.first)
        StubNetwork.install(status: 200, json: "{}")
        store.toggle(api: api, habit)
        for _ in 0..<50 where !StubNetwork.requests.contains(where: { $0.httpMethod == "POST" }) {
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        XCTAssertFalse(StubNetwork.requests.contains { $0.httpMethod == "DELETE" },
                       "yesterday's check-in was deleted")
        XCTAssertTrue(StubNetwork.requests.contains { $0.httpMethod == "POST" && $0.url?.path == "/api/entries" },
                      "today was not checked in")
    }

    /// L1: a new day (midnight, or back in front) clears yesterday's ticks.
    func testANewDayClearsYesterdaysTicks() async throws {
        let store = try await habitsTicked(on: "2000-01-01")
        serve("")
        store.startNewDayIfNeeded()
        XCTAssertTrue(store.checkedToday.isEmpty, "yesterday's ticks showed as today's")
        XCTAssertFalse(store.todayComplete)
    }

    /// L1: the ticks are saved with the day they were made, not stamped with today.
    func testTicksAreSavedWithTheirOwnDay() async throws {
        let store = try await habitsTicked(on: "2000-01-01")
        let uid = try XCTUnwrap(api.currentUserId)
        struct Checks: Decodable { let day: String }
        var saved: String?
        for _ in 0..<50 {
            saved = DiskCache.load(Checks.self, key: "habits.checks", userId: uid)?.day
            if saved == "2000-01-01" { break }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        XCTAssertEqual(saved, "2000-01-01", "yesterday's ticks were saved as today's")
        _ = store
    }

    private func waitFor(_ check: () -> Bool) async throws {
        for _ in 0..<50 where !check() { try await Task.sleep(nanoseconds: 20_000_000) }
    }

    private func patches(_ path: String) -> [String] {
        StubNetwork.requests.filter { $0.httpMethod == "PATCH" && $0.url?.path == path }
            .map { String(decoding: StubNetwork.body(of: $0), as: UTF8.self) }
    }

    /// L7: ticked done, then back out of the list within four seconds: «تراجع» showed but
    /// the store was gone, so it did nothing and the offer left as if it had worked.
    func testUndoAfterLeavingTheListStillTakesTheTickBack() async throws {
        serve(Self.milk)
        var store: ItemsStore? = ItemsStore(list: "tasks")
        await store?.load(api: api)
        let milk = try XCTUnwrap(store?.items.first)
        store?.toggle(api: api, milk)
        try await waitFor { patches("/api/items/t1").count == 1 }
        store = nil
        UndoCenter.shared.undo()
        try await waitFor { patches("/api/items/t1").count == 2 }
        XCTAssertEqual(patches("/api/items/t1").count, 2, "«تراجع» after leaving the list did nothing")
        XCTAssertTrue(patches("/api/items/t1").last?.contains("\"done\":false") == true)
    }
}
