import XCTest
@testable import SandyApp

/// A dimmer's slider read the level once, when it appeared: set by voice or by a scene, the
/// light moved and the slider did not. It follows the device now, except under a finger.
final class DimmerSyncTests: XCTestCase {
    func testTheSliderFollowsANewLevel() {
        XCTAssertEqual(DeviceCard.sliderLevel(state: "70", min: 0, current: 20, dragging: false), 70)
    }

    func testAFingerOnTheSliderIsNotOverruled() {
        XCTAssertEqual(DeviceCard.sliderLevel(state: "70", min: 0, current: 20, dragging: true), 20)
    }

    func testAnUnreadableStateKeepsTheSlider() {
        XCTAssertEqual(DeviceCard.sliderLevel(state: "on", min: 0, current: 40, dragging: false), 40)
    }
}
