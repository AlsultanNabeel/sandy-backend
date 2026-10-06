import XCTest
@testable import SandyApp

/// A photo that did not save says so where the user is: inside the add sheet. The message
/// used to go to the album screen underneath the sheet, out of sight.
@MainActor
final class PhotoAddTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    func testAFailedSaveHandsTheSheetItsMessage() async {
        StubNetwork.install(status: 413, json: #"{"error":"too_big","message":"الصورة كبيرة"}"#)
        let error = await PhotosStore().add(api: TestClient.make(), jpeg: Data([0xFF, 0xD8]),
                                            name: "", album: "")
        XCTAssertEqual(error, "الصورة كبيرة")
    }

    func testASavedPhotoHasNoMessage() async {
        StubNetwork.install(json: #"{"ok": true, "items": []}"#)
        let error = await PhotosStore().add(api: TestClient.make(), jpeg: Data([0xFF, 0xD8]),
                                            name: "", album: "")
        XCTAssertNil(error)
    }
}
