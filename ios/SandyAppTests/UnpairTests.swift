import XCTest
@testable import SandyApp

/// Unlinking a robot that is off leaves its Wi-Fi password and keys on it: the server says
/// `board_wiped: false`. The robot card's unlink dropped that answer and said nothing.
@MainActor
final class UnpairTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    private let node = NodeItem(nodeId: "abc", label: "ساندي", capabilities: [], outputs: [],
                                firmwareVersion: "", online: false, lastSeen: "", pairedAt: "",
                                telemetry: nil)

    func testAnUnlinkThatLeftTheBoardAsItWasSaysSo() async {
        StubNetwork.install { request in
            request.httpMethod == "DELETE"
                ? (200, Data(#"{"ok":true,"board_wiped":false}"#.utf8))
                : (200, Data(#"{"items":[]}"#.utf8))
        }
        let store = DevicesStore()
        await store.unpair(api: TestClient.make(), node: node)
        XCTAssertEqual(store.notice, LanguageManager.shared.s("account.sell.offline"))
    }

    func testAWipedBoardNeedsNoWarning() async {
        StubNetwork.install { request in
            request.httpMethod == "DELETE"
                ? (200, Data(#"{"ok":true,"board_wiped":true}"#.utf8))
                : (200, Data(#"{"items":[]}"#.utf8))
        }
        let store = DevicesStore()
        await store.unpair(api: TestClient.make(), node: node)
        XCTAssertEqual(store.notice, "")
    }
}
