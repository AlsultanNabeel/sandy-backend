import XCTest
@testable import SandyApp

/// The server marks one-shot values (`meta.momentary`); the card draws them as buttons and
/// keeps a picker only for the remembered choices.
final class MomentaryTests: XCTestCase {
    private func device(_ meta: [String: Any]) -> DeviceItem {
        DeviceItem(name: "room_music", label: "موسيقى", room: "", controlType: "enum",
                   transport: DeviceTransport.from([:]), meta: meta, state: "", online: true,
                   lastSeen: "")
    }

    func testMusicKeepsItsPlayStateAndHasNextAndPreviousAsButtons() {
        let d = device(["values": ["stop", "pause", "resume", "next", "prev"],
                        "momentary": ["next", "prev"]])
        XCTAssertEqual(d.momentaryValues, ["next", "prev"])
        XCTAssertEqual(d.choiceValues, ["stop", "pause", "resume"])
    }

    func testAPhotoIsOnlyAButton() {
        let d = device(["values": ["take"], "momentary": ["take"]])
        XCTAssertEqual(d.momentaryValues, ["take"])
        XCTAssertTrue(d.choiceValues.isEmpty)
    }

    func testAnOlderServerWithoutTheMarkKeepsThePicker() {
        let d = device(["values": ["small", "large"]])
        XCTAssertTrue(d.momentaryValues.isEmpty)
        XCTAssertEqual(d.choiceValues, ["small", "large"])
    }
}
