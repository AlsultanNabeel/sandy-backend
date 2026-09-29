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
        let client = APIClient(baseURL: "https://example.test")
        client.token = makeJWT(payloadJSON: "{\"user_id\":\"abc123\",\"role\":\"user\"}")
        XCTAssertEqual(client.currentUserId, "abc123")
    }

    func testCurrentUserIdIsNilWithoutToken() {
        let client = APIClient(baseURL: "https://example.test")
        client.token = nil
        XCTAssertNil(client.currentUserId)
    }

    func testCurrentUserIdIsNilForMalformedToken() {
        let client = APIClient(baseURL: "https://example.test")
        client.token = "not.a.valid-token"
        XCTAssertNil(client.currentUserId)
    }

    func testCurrentUserIdIsNilWhenPayloadHasNoUserId() {
        let client = APIClient(baseURL: "https://example.test")
        client.token = makeJWT(payloadJSON: "{\"role\":\"guest\"}")
        XCTAssertNil(client.currentUserId)
    }

    /// Unpadded base64URL payload (length not a multiple of 4) must be re-padded.
    func testCurrentUserIdHandlesUnpaddedBase64URL() {
        let client = APIClient(baseURL: "https://example.test")
        client.token = makeJWT(payloadJSON: "{\"user_id\":\"x\"}")
        XCTAssertEqual(client.currentUserId, "x")
    }
}
