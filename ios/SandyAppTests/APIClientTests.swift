import XCTest
@testable import SandyApp

/// First unit tests for the app. They cover the network-free logic in the
/// networking core — the JWT payload decode `APIClient.currentUserId` does with
/// no server, no Keychain round-trip and no async — so the suite runs fast and
/// deterministically. This is the seed target: as stores adopt `APIClientProtocol`
/// (see `APIClientProtocol.swift`), their optimistic-update paths get mocked and
/// added here.
final class APIClientTests: XCTestCase {

    /// Build an unsigned JWT (header.payload.sig) whose middle segment is the
    /// given JSON, base64url-encoded exactly the way a real token is. The client
    /// only *decodes* the payload for display; it never verifies the signature,
    /// so a dummy "sig" segment is enough.
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

    /// The payload is base64URL with the padding stripped (real tokens do this);
    /// currentUserId must re-pad before decoding. A single-char user_id makes the
    /// payload length land on a non-multiple of 4, exercising that path.
    func testCurrentUserIdHandlesUnpaddedBase64URL() {
        let client = APIClient(baseURL: "https://example.test")
        client.token = makeJWT(payloadJSON: "{\"user_id\":\"x\"}")
        XCTAssertEqual(client.currentUserId, "x")
    }
}
