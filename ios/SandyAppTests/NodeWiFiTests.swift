import XCTest
@testable import SandyApp

/// After a network change the screen judged success from the node it was opened with, an
/// old copy: a move that worked read as «rolled back».
final class NodeWiFiTests: XCTestCase {
    private func node(ssid: String) throws -> NodeItem {
        let rows = try JSONSerialization.data(withJSONObject: ["ssid": ssid])
        let tele = NodeTelemetry(try JSONSerialization.jsonObject(with: rows) as? [String: Any])
        return NodeItem(nodeId: "abc", label: "", capabilities: [], outputs: [], firmwareVersion: "",
                        online: true, lastSeen: "", pairedAt: "", telemetry: tele)
    }

    func testTheResultIsReadFromTheFreshNode() throws {
        XCTAssertTrue(NodeWiFiView.landed(on: "Office", fresh: try node(ssid: "Office")))
        XCTAssertFalse(NodeWiFiView.landed(on: "Office", fresh: try node(ssid: "Home")))
        XCTAssertFalse(NodeWiFiView.landed(on: "Office", fresh: nil))
    }
}
