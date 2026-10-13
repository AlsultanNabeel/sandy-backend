import XCTest
@testable import SandyApp

/// A brownout used to clear the crash count and was shown nowhere; now the brain says its
/// power is weak (`power_weak`) after a few in a row, and the robot card says so.
final class RobotLivePowerTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    func testWeakPowerIsRead() async throws {
        StubNetwork.install(json: #"""
            {"items":[{"node_id":"abc","online":true,
                       "telemetry":{"power_weak":true,"brownouts":3}}]}
            """#)
        let live = try await TestClient.make().getRobotLive()
        let node = try XCTUnwrap(live.nodes.first)
        XCTAssertTrue(node.powerWeak)
    }

    func testAnOlderBoardIsNotWeak() async throws {
        StubNetwork.install(json: #"{"items":[{"node_id":"abc","online":true,"telemetry":{}}]}"#)
        let live = try await TestClient.make().getRobotLive()
        let node = try XCTUnwrap(live.nodes.first)
        XCTAssertFalse(node.powerWeak)
    }
}
