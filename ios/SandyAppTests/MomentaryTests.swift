import XCTest
@testable import SandyApp

/// The server marks one-shot values (`meta.momentary`); the card draws them as buttons and
/// keeps a picker only for the remembered choices.
final class MomentaryTests: XCTestCase {
    private func device(_ meta: [String: Any]) -> DeviceItem {
        DeviceItem(name: "sandy_part", label: "قطعة", room: "", controlType: "enum",
                   transport: DeviceTransport.from([:]), meta: meta, state: "", online: true,
                   lastSeen: "")
    }

    func testRememberedValuesKeepAPickerAndOneShotsAreButtons() {
        let d = device(["values": ["off", "low", "high", "nod", "shake"],
                        "momentary": ["nod", "shake"]])
        XCTAssertEqual(d.momentaryValues, ["nod", "shake"])
        XCTAssertEqual(d.choiceValues, ["off", "low", "high"])
    }

    func testAOneShotOnlyPartIsOnlyButtons() {
        let d = device(["values": ["beep"], "momentary": ["beep"]])
        XCTAssertEqual(d.momentaryValues, ["beep"])
        XCTAssertTrue(d.choiceValues.isEmpty)
    }

    func testAnOlderServerWithoutTheMarkKeepsThePicker() {
        let d = device(["values": ["small", "large"]])
        XCTAssertTrue(d.momentaryValues.isEmpty)
        XCTAssertEqual(d.choiceValues, ["small", "large"])
    }
}
