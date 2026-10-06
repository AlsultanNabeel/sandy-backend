import XCTest
@testable import SandyApp

/// A camera that is off answers `camera_offline`; the screen showed the general failure.
/// A robot part's menu offered edit (which did nothing) and delete (which came back with
/// the next heartbeat); now it renames.
@MainActor
final class RobotPartsTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    func testAnOfflineCameraHasItsOwnSentence() {
        XCTAssertEqual(CameraView.errorKey("camera_offline"), "robot.control.camera.error.camera_offline")
        XCTAssertEqual(CameraView.errorKey("something_else"), "robot.control.camera.failed")
        XCTAssertNotEqual(LanguageManager.shared.s("robot.control.camera.error.camera_offline"),
                          "robot.control.camera.error.camera_offline", "the sentence is missing")
    }

    func testRenamingARobotPartSendsTheNewLabel() async throws {
        StubNetwork.install { _ in (200, Data(#"{"ok":true,"items":[]}"#.utf8)) }
        let part = DeviceItem(name: "sandy_head", label: "رقبة ساندي", room: "", controlType: "dimmer",
                              transport: DeviceTransport.from([:]), meta: [:], state: "",
                              online: true, lastSeen: "")
        try await DevicesStore().rename(api: TestClient.make(), device: part, label: "راسها")
        let patch = try XCTUnwrap(StubNetwork.requests.first { $0.httpMethod == "PATCH" })
        XCTAssertEqual(patch.url?.path, "/api/devices/sandy_head")
        let body = try JSONSerialization.jsonObject(with: StubNetwork.body(of: patch)) as? [String: Any]
        XCTAssertEqual(body?["label"] as? String, "راسها")
    }
}
