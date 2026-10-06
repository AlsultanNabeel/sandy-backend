import XCTest
@testable import SandyApp

/// After a network change the screen judged success from the node it was opened with, an
/// old copy: a move that worked read as «rolled back».
final class NodeWiFiTests: XCTestCase {
    private func node(ssid: String, camSSID: String = "") throws -> NodeItem {
        let rows = try JSONSerialization.data(withJSONObject: ["ssid": ssid, "cam_ssid": camSSID])
        let tele = NodeTelemetry(try JSONSerialization.jsonObject(with: rows) as? [String: Any])
        return NodeItem(nodeId: "abc", label: "", capabilities: [], outputs: [], firmwareVersion: "",
                        online: true, lastSeen: "", pairedAt: "", telemetry: tele)
    }

    func testTheResultIsReadFromTheFreshNode() throws {
        XCTAssertTrue(NodeWiFiView.landed(on: "Office", fresh: try node(ssid: "Office"), board: "brain"))
        XCTAssertFalse(NodeWiFiView.landed(on: "Office", fresh: try node(ssid: "Home"), board: "brain"))
        XCTAssertTrue(NodeWiFiView.landed(on: "Office", fresh: try node(ssid: "Home", camSSID: "Office"),
                                          board: "camera"))
        XCTAssertFalse(NodeWiFiView.landed(on: "Office", fresh: nil, board: "brain"))
    }

    func testTheBoardCanBeChosenAgainAfterAFailedTry() {
        XCTAssertFalse(NodeWiFiView.boardLocked(during: .done(success: false)))
        XCTAssertFalse(NodeWiFiView.boardLocked(during: .idle))
        XCTAssertTrue(NodeWiFiView.boardLocked(during: .trying(secondsLeft: 5)))
    }
}
