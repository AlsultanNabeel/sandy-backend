import XCTest
@testable import SandyApp

/// The node exactly as the server sends it (`node_store._public`): the brain's heartbeat
/// always carries `faults` and `stacks` as maps, and outputs are `{id, kind}` objects.
final class NodeDecodeTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    private let body = #"""
    {"items":[{"node_id":"abc123","label":"ساندي","capabilities":["relay"],
      "outputs":[{"id":"sandy_face","kind":"pwm"},{"id":"cam_snapshot","kind":"camera"}],
      "firmware_version":"0.11.6","online":true,"last_seen":"","paired_at":"",
      "telemetry":{"ssid":"Home","ip":"192.168.1.5","cam_ip":"192.168.1.6",
                   "cam_stream_key":"k","mic_l":3,"faults":{},"stacks":{"voice":812}}}],
     "demo":false}
    """#

    private func node() async throws -> NodeItem {
        StubNetwork.install(json: body)
        let nodes = try await TestClient.make().getNodes()
        return try XCTUnwrap(nodes.items.first)
    }

    func testTheTelemetrySurvivesTheMapsInIt() async throws {
        let n = try await node()
        XCTAssertEqual(n.telemetry?.ssid, "Home", "one map in the heartbeat emptied all of it")
        XCTAssertEqual(n.telemetry?.camIP, "192.168.1.6")
        XCTAssertEqual(n.telemetry?.micLeft, 3)
    }

}
