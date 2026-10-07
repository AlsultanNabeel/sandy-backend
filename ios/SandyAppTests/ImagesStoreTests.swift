import XCTest
import UIKit
@testable import SandyApp

/// M12: switching the images mode cleared the result but left the request running, so a
/// picture drawn for «generate» landed under «describe».
@MainActor
final class ImagesStoreTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    func testSwitchingModeCallsOffTheRunningRequest() async {
        let png = UIGraphicsImageRenderer(size: CGSize(width: 2, height: 2)).pngData { _ in }
        let uri = "data:image/png;base64," + png.base64EncodedString()
        StubNetwork.install(json: #"{"url":"\#(uri)"}"#)
        StubNetwork.delay("POST", by: 0.4)
        let store = ImagesStore()
        let drawing = Task { await store.generate(api: TestClient.make(), prompt: "قطة") }
        try? await Task.sleep(nanoseconds: 100_000_000)
        store.reset()                                   // the mode switched
        await drawing.value
        try? await Task.sleep(nanoseconds: 500_000_000) // past the answer's arrival
        XCTAssertNil(store.resultImage, "the old mode's picture showed under the new one")
        XCTAssertFalse(store.loading)
    }
}
