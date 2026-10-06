import XCTest
@testable import SandyApp

/// Audit batch four: the outbox keeps what the server could not take yet, and drops only
/// what the server refused for good.
@MainActor
final class OutboxTests: XCTestCase {
    private var api: APIClient!

    override func setUp() async throws {
        try await super.setUp()
        api = TestClient.make()
        api.token = SessionTests.token("outbox-\(UUID().uuidString.prefix(8))")
    }

    override func tearDown() async throws {
        Outbox.shared.discard()
        Outbox.shared.now = Date.init
        StubNetwork.uninstall()
        try await super.tearDown()
    }

    private func answer(_ status: Int) {
        StubNetwork.install(status: status, json: "{}")
    }

    private func writes(_ method: String = "POST") -> Int {
        StubNetwork.requests.filter { $0.httpMethod == method }.count
    }

    /// Sends one write; true when its caller was told it was refused.
    private func send(_ method: String = "POST", _ path: String = "/api/items") async -> Bool {
        do {
            try await Outbox.shared.send(api, path, method: method,
                                         body: method == "DELETE" ? nil : ["text": "حليب"])
            return false
        } catch {
            return true
        }
    }

    /// K2: a deploy or a restart answers 503 for a moment; the change was dropped for good.
    func testAServerErrorKeepsTheChange() async {
        answer(503)
        let refused = await send()
        XCTAssertFalse(refused, "a passing server error undid the change")
        XCTAssertEqual(Outbox.shared.count, 1, "the change left the queue on a 503")
    }

    /// K2: a request that timed out on the server's side is tried again, not dropped.
    func testATimeoutKeepsTheChange() async {
        answer(408)
        let refused = await send()
        XCTAssertFalse(refused)
        XCTAssertEqual(Outbox.shared.count, 1, "the change left the queue on a 408")
    }

    /// K2: too many requests means later, not never.
    func testTooManyRequestsKeepsTheChange() async {
        answer(429)
        let refused = await send()
        XCTAssertFalse(refused)
        XCTAssertEqual(Outbox.shared.count, 1, "the change left the queue on a 429")
    }

    /// K2: the session ended; the change stays for its own account.
    func testAnEndedSessionKeepsTheChange() async {
        answer(401)
        _ = await send()
        XCTAssertEqual(Outbox.shared.count, 1, "the change left the queue on a 401")
    }

    /// K2: a 429 waits as long as the server asked before anything is sent again.
    func testTooManyRequestsWaitsWhatTheServerAsked() async throws {
        answer(429)
        StubURLProtocol.headers = ["Retry-After": "120"]
        _ = await send()
        let wait = try XCTUnwrap(Outbox.shared.notBefore).timeIntervalSinceNow
        XCTAssertGreaterThan(wait, 110, "the server's wait was not kept")
        answer(200)
        await Outbox.shared.drain(api)
        XCTAssertEqual(writes(), 0, "sent again before the server's wait was over")
        XCTAssertEqual(Outbox.shared.count, 1)
    }

    /// K2: the pause ends and the kept change goes out by itself.
    func testAKeptChangeGoesOutWhenThePauseEnds() async throws {
        answer(503)
        _ = await send()
        XCTAssertNotNil(Outbox.shared.notBefore)
        answer(200)
        Outbox.shared.stopWaiting()
        await Outbox.shared.drain(api)
        XCTAssertEqual(writes(), 1)
        XCTAssertTrue(Outbox.shared.isEmpty)
    }

    /// K2: a change the server keeps answering «not now» does not hold the queue for ever:
    /// it is parked with a notice, and the rest goes on.
    func testAChangeThatKeepsFailingIsParkedNotLost() async throws {
        StubNetwork.install { req in (req.url?.path == "/api/items/stuck" ? 503 : 200, Data("{}".utf8)) }
        _ = await send("PATCH", "/api/items/stuck")
        for _ in 1..<Outbox.maxTries {
            Outbox.shared.stopWaiting()
            await Outbox.shared.drain(api)
        }
        XCTAssertEqual(Outbox.shared.parkedCount, 1, "a change that kept failing was dropped or still blocks")
        XCTAssertTrue(Outbox.shared.isEmpty)
        XCTAssertTrue(Outbox.shared.hasUnsent, "a sign-out would lose it without a warning")
        XCTAssertEqual(NoticeCenter.shared.notice?.text, LanguageManager.shared.s("blocks.outboxParked"))
        _ = await send()
        XCTAssertEqual(writes(), 1, "the change behind it was held up")
    }

    /// K2: or after a day of «not now», however few tries that was.
    func testAChangeFailingForADayIsParked() async throws {
        answer(503)
        _ = await send()
        Outbox.shared.now = { Date().addingTimeInterval(Outbox.maxAge + 60) }
        Outbox.shared.stopWaiting()
        await Outbox.shared.drain(api)
        XCTAssertEqual(Outbox.shared.parkedCount, 1)
        XCTAssertTrue(Outbox.shared.isEmpty)
    }

    /// K2: back in front, a parked change is tried again and goes out once the server is back.
    func testAParkedChangeIsTriedAgainBackInFront() async throws {
        answer(503)
        _ = await send()
        Outbox.shared.now = { Date().addingTimeInterval(Outbox.maxAge + 60) }
        Outbox.shared.stopWaiting()
        await Outbox.shared.drain(api)
        XCTAssertEqual(Outbox.shared.parkedCount, 1)
        Outbox.shared.now = Date.init
        answer(200)
        await Outbox.shared.retryParked(api)
        XCTAssertEqual(writes(), 1)
        XCTAssertFalse(Outbox.shared.hasUnsent)
    }

    /// A change the server refuses for good is dropped and its caller told, so it is undone.
    func testARefusedChangeIsDroppedAndItsCallerTold() async {
        answer(400)
        let refused = await send()
        XCTAssertTrue(refused)
        XCTAssertTrue(Outbox.shared.isEmpty)
    }
}
