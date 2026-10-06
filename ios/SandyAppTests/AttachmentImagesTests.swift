import XCTest
@testable import SandyApp

/// Attachments are deleted thirty days after they are saved: an old chat must say the image
/// expired, not sit on a loading placeholder for ever.
@MainActor
final class AttachmentImagesTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    func testAnAttachmentTheServerNoLongerHasReadsAsExpired() async {
        StubNetwork.install(status: 404, json: #"{"error": "not_found"}"#)
        let result = await AttachmentImages().load("gone-\(UUID().uuidString)", api: TestClient.make())
        XCTAssertEqual(result, .expired)
    }

    func testAnOutageIsNotAnExpiredImage() async {
        StubNetwork.install(status: 503, json: #"{"error": "down"}"#)
        let result = await AttachmentImages().load("x-\(UUID().uuidString)", api: TestClient.make())
        XCTAssertEqual(result, .failed)
    }
}
