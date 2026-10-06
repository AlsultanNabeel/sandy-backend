import XCTest
@testable import SandyApp

/// Audit batch four, L10: a long sentence sent with no network was wiped from the field.
final class AskBarTests: XCTestCase {
    func testAFailedSendGivesTheWordsBack() {
        XCTAssertEqual(AskBar.textAfterFailure(sent: "ذكّريني بالدوا الساعة تسعة", typed: ""),
                       "ذكّريني بالدوا الساعة تسعة")
    }

    func testWordsTypedSinceAreKept() {
        XCTAssertEqual(AskBar.textAfterFailure(sent: "قديم", typed: "جديد"), "جديد")
    }
}
