import XCTest
@testable import SandyApp

/// Audit batch four: the daily card tries again after a failure and says when an answer
/// did not go.
@MainActor
final class DailyNudgeTests: XCTestCase {
    override func tearDown() {
        StubNetwork.uninstall()
        super.tearDown()
    }

    private func client() -> APIClient {
        let api = TestClient.make()
        api.token = SessionTests.token("nudge-\(UUID().uuidString.prefix(8))")
        return api
    }

    /// L11: the first fetch failed (no network at launch) and the card never came that day.
    func testAFailedFetchIsTriedAgain() async {
        let api = client()
        let store = DailyNudgeStore()
        StubNetwork.install(status: StubNetwork.offline, json: "{}")
        await store.loadIfNeeded(api: api)
        XCTAssertNil(store.nudge)
        StubNetwork.install(status: 200, json: #"{"kind":"agenda","text":"يومك خفيف"}"#)
        await store.loadIfNeeded(api: api)
        XCTAssertEqual(store.nudge?.text, "يومك خفيف", "a failed first fetch kept the card away all day")
    }

    /// L11: an answer that did not go stopped the spinner and said nothing.
    func testAFailedAnswerIsShownAndKept() async {
        let store = DailyNudgeStore()
        store.nudge = DailyNudge(kind: .question, qid: "q1", text: "شو بتحب تقرا؟")
        store.answer = "روايات"
        StubNetwork.install(status: 500, json: "{}")
        await store.submit(api: client())
        XCTAssertTrue(store.sendFailed, "a failed answer said nothing")
        XCTAssertFalse(store.answered)
        XCTAssertEqual(store.answer, "روايات")
        StubNetwork.install(status: 200, json: "{}")
        await store.submit(api: client())
        XCTAssertFalse(store.sendFailed)
        XCTAssertTrue(store.answered)
    }
}
