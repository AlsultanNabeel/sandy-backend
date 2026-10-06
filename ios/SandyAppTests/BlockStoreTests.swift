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

    /// GETs answer `rows` after `delay`; writes answer at once.
    private func serve(_ rows: String, delay: TimeInterval = 0) {
        StubNetwork.install { req in
            (200, Data((req.httpMethod == "GET" ? "{\"items\":[\(rows)]}" : "{}").utf8))
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
}
