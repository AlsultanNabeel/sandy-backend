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

    /// An unsigned token for `uid`: the client reads the account from it, never checks it.
    static func token(_ uid: String) -> String {
        func b64url(_ s: String) -> String {
            Data(s.utf8).base64EncodedString().replacingOccurrences(of: "+", with: "-")
                .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        }
        return "\(b64url("{\"alg\":\"HS256\"}")).\(b64url("{\"user_id\":\"\(uid)\"}")).sig"
    }

    /// Waits for the cache's serial queue to write what was queued before.
    private func settle(_ check: () -> Bool) async {
        for _ in 0..<50 where !check() { try? await Task.sleep(nanoseconds: 20_000_000) }
    }

    private func sentWrites() -> Int {
        StubNetwork.requests.filter { $0.url?.path == "/api/items" && $0.httpMethod == "POST" }.count
    }

    /// K1: the session ended with a change still unsent: it waits for its own account,
    /// is never sent for another one, and is not wiped by the sign-out.
    func testAnEndedSessionKeepsItsUnsentChangeForItsOwnerOnly() async throws {
        let owner = "owner-\(UUID().uuidString.prefix(8))", other = "other-\(UUID().uuidString.prefix(8))"
        defer { DiskCache.remove(key: Outbox.fileKey, userId: owner) }
        let api = TestClient.make()
        api.token = Self.token(owner)
        StubNetwork.install(status: StubNetwork.offline, json: "{}")
        try await Outbox.shared.send(api, "/api/items", method: "POST", body: ["text": "حليب"])
        XCTAssertEqual(Outbox.shared.count, 1)

        Outbox.shared.signedOut(discarding: false)
        api.token = nil
        DiskCache.clearAll(except: Outbox.fileKey)
        await settle { DiskCache.load([Outbox.Op].self, key: Outbox.fileKey, userId: owner)?.count == 1 }
        XCTAssertEqual(DiskCache.load([Outbox.Op].self, key: Outbox.fileKey, userId: owner)?.count, 1,
                       "signing out wiped the change made offline")

        StubNetwork.install(status: 200, json: "{}")
        await Outbox.shared.drain(api)
        XCTAssertEqual(sentWrites(), 0, "sent with no one signed in")
        api.token = Self.token(other)
        await Outbox.shared.drain(api)
        XCTAssertEqual(sentWrites(), 0, "another account sent it")
        Outbox.shared.signedOut(discarding: true)
        api.token = Self.token(owner)
        await Outbox.shared.drain(api)
        XCTAssertEqual(sentWrites(), 1, "the owner's change never went out")
        XCTAssertTrue(Outbox.shared.isEmpty)
        Outbox.shared.signedOut(discarding: false)
    }
}
