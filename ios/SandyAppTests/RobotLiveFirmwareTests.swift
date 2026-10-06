import XCTest
@testable import SandyApp

/// The server keeps the camera's and the room node's own versions (`cam_fw`, `room_fw`);
/// the robot card showed only the brain's, so a camera left behind by an update was invisible.
final class RobotLiveFirmwareTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    func testEveryBoardSVersionIsRead() async throws {
        StubNetwork.install(json: #"""
            {"items":[{"node_id":"abc","firmware_version":"0.11.6","online":true,
                       "telemetry":{"cam_fw":"0.4.2","room_fw":"0.3.1"}}]}
            """#)
        let live = try await TestClient.make().getRobotLive()
        let node = try XCTUnwrap(live.nodes.first)
        XCTAssertEqual(node.firmwareVersion, "0.11.6")
        XCTAssertEqual(node.cameraFirmware, "0.4.2")
        XCTAssertEqual(node.roomFirmware, "0.3.1")
    }
}
