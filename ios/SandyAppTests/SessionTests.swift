import XCTest
@testable import SandyApp

/// Audit batch three: the session, sign-out and switching accounts.
@MainActor
final class SessionTests: XCTestCase {
    override func tearDown() {
        StubNetwork.uninstall()
        super.tearDown()
    }

    /// K1: the server renews a day-old token; a week in, the user was signed out instead.
    func testARenewedTokenIsKept() async throws {
        let api = TestClient.make()
        api.token = "old"
        StubNetwork.install(status: 200, json: "[]")
        StubURLProtocol.headers = [APIClient.renewedHeader: "new"]
        _ = try? await api.getFeatures()
        XCTAssertEqual(api.token, "new")
    }

    /// K1: a renewal for a request sent before a sign-out or a switch is not taken.
    func testARenewalForAnotherSessionIsNotTaken() {
        let api = TestClient.make()
        api.token = "second"
        let resp = HTTPURLResponse(url: URL(string: "https://example.test")!, statusCode: 200,
                                   httpVersion: nil, headerFields: [APIClient.renewedHeader: "first-renewed"])!
        api.keepRenewed(resp, sent: "first")
        XCTAssertEqual(api.token, "second")
        api.token = nil
        api.keepRenewed(resp, sent: "first")
        XCTAssertNil(api.token, "a renewal signed a signed-out phone back in")
    }
}
