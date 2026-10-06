import XCTest
@testable import SandyApp

/// A subscriber stays a subscriber when one refresh fails (it used to become «unknown»
/// and lock the paid features until the next good one).
@MainActor
final class SubscriptionTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    func testAFailedRefreshKeepsTheKnownStatus() async {
        let subs = SubscriptionManager()
        let api = TestClient.make()
        StubNetwork.install(json: #"{"status":"active","plan":"monthly","is_subscriber":true}"#)
        await subs.refresh(api: api)
        XCTAssertTrue(subs.isSubscriber)

        StubNetwork.install(status: 503, json: #"{"error":"down"}"#)
        await subs.refresh(api: api)
        XCTAssertTrue(subs.isSubscriber, "one failed refresh locked a paying user out")
    }
}
