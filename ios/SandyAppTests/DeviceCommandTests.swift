import XCTest
@testable import SandyApp

/// The server answers 200 `{"ok":true,"sent":false}` when the command did not reach the
/// board (it is off, or the broker is down). The app and Siri used to say «done».
final class DeviceCommandTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    func testACommandThatDidNotReachTheBoardIsAnError() async {
        StubNetwork.install(json: #"{"ok":true,"sent":false}"#)
        do {
            try await TestClient.make().controlDevice(name: "lamp", action: "on")
            XCTFail("a command that never left the server was reported as done")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "not_sent")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testIrLearningThatDidNotReachTheBoardIsAnError() async {
        StubNetwork.install(json: #"{"ok":true,"sent":false}"#)
        do {
            try await TestClient.make().nodeIrLearnStart(nodeId: "abc")
            XCTFail("learning that never started was reported as started")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "not_sent")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testASentCommandOrAnOlderAnswerIsFine() async throws {
        StubNetwork.install(json: #"{"ok":true,"sent":true}"#)
        try await TestClient.make().controlDevice(name: "lamp", action: "on")
        StubNetwork.install(json: #"{"ok":true}"#)
        try await TestClient.make().controlDevice(name: "lamp", action: "on")
    }
}
