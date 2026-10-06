import XCTest
@testable import SandyApp

/// Network-free tests for the JWT payload decode behind `APIClient.currentUserId`.
final class APIClientTests: XCTestCase {

    /// Unsigned JWT with the given JSON payload; the client never verifies the signature.
    private func makeJWT(payloadJSON: String) -> String {
        func b64url(_ s: String) -> String {
            Data(s.utf8).base64EncodedString()
                .replacingOccurrences(of: "+", with: "-")
                .replacingOccurrences(of: "/", with: "_")
                .replacingOccurrences(of: "=", with: "")
        }
        return "\(b64url("{\"alg\":\"HS256\"}")).\(b64url(payloadJSON)).sig"
    }

    func testCurrentUserIdDecodesUserId() {
        let client = TestClient.make()
        client.token = makeJWT(payloadJSON: "{\"user_id\":\"abc123\",\"role\":\"user\"}")
        XCTAssertEqual(client.currentUserId, "abc123")
    }

    func testCurrentUserIdIsNilWithoutToken() {
        let client = TestClient.make()
        client.token = nil
        XCTAssertNil(client.currentUserId)
    }

    func testCurrentUserIdIsNilForMalformedToken() {
        let client = TestClient.make()
        client.token = "not.a.valid-token"
        XCTAssertNil(client.currentUserId)
    }

    func testCurrentUserIdIsNilWhenPayloadHasNoUserId() {
        let client = TestClient.make()
        client.token = makeJWT(payloadJSON: "{\"role\":\"guest\"}")
        XCTAssertNil(client.currentUserId)
    }

    /// Unpadded base64URL payload (length not a multiple of 4) must be re-padded.
    func testCurrentUserIdHandlesUnpaddedBase64URL() {
        let client = TestClient.make()
        client.token = makeJWT(payloadJSON: "{\"user_id\":\"x\"}")
        XCTAssertEqual(client.currentUserId, "x")
    }
}

/// A client that touches nothing outside the test: its token lives in memory and the
/// server address is not mirrored for the widget and the share extension.
enum TestClient {
    static func make(baseURL: String = "https://example.test") -> APIClient {
        APIClient(baseURL: baseURL, tokenStore: MemoryTokenStore(), mirrorsShared: false)
    }
}

final class MemoryTokenStore: TokenStore {
    private var value: String?
    func load() -> String? { value }
    func save(_ token: String?) { value = token }
}

/// The client tests used to sign the app out: a fake token went into the shared Keychain
/// (and `nil` deleted the real one), and the fake address replaced the real one for the
/// widget and the share extension.
final class APIClientSideEffectTests: XCTestCase {
    func testATestClientLeavesTheRealTokenAndAddressAlone() {
        let defaults = UserDefaults(suiteName: SharedAuth.appGroup)
        let tokenBefore = Keychain.loadToken()
        let addressBefore = defaults?.string(forKey: SharedAuth.baseURLKey)

        let client = TestClient.make(baseURL: "https://elsewhere.test")
        client.token = "fake.jwt.token"
        client.token = nil
        client.baseURL = "https://elsewhere-again.test"

        XCTAssertEqual(Keychain.loadToken(), tokenBefore)
        XCTAssertEqual(defaults?.string(forKey: SharedAuth.baseURLKey), addressBefore)
    }
}
