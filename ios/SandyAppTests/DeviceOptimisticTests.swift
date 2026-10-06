import XCTest
@testable import SandyApp

/// A switch flipped on stays on while its command is on the way: a refresh that answered
/// with the old state (the robot test screen polls every five seconds) used to flip it back.
@MainActor
final class DeviceOptimisticTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    func testARefreshDuringACommandKeepsWhatWasAsked() async throws {
        StubNetwork.install { request in
            let path = request.url!.path
            if request.httpMethod == "POST" {
                return (200, Data(#"{"ok":true,"sent":true}"#.utf8))
            }
            if path == "/api/devices" {
                return (200, Data(#"{"items":[{"name":"lamp","label":"ضو","control_type":"switch","state":"off","transport":{}}]}"#.utf8))
            }
            return (200, Data(#"{"items":[]}"#.utf8))
        }
        StubNetwork.delay("POST", by: 1.0)                    // the command is slow
        let api = TestClient.make()
        let store = DevicesStore()
        await store.load(api: api)
        let lamp = try XCTUnwrap(store.devices.first)
        store.control(api: api, device: lamp, action: "on")
        await store.load(api: api)                            // answers «off»: the old state
        XCTAssertEqual(store.devices.first?.state, "on", "the refresh undid the switch")
    }
}
