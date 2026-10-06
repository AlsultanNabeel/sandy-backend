import XCTest
@testable import SandyApp

/// One reading of a typed number everywhere: Arabic-Indic and Persian digits are digits,
/// the plain comma and the Arabic thousands mark group thousands, and the point or the
/// Arabic decimal mark starts the fraction.
final class DigitsTests: XCTestCase {
    func testArabicAndPersianDigitsBecomeLatin() {
        XCTAssertEqual(Digits.latin("١٥٠٠"), "1500")
        XCTAssertEqual(Digits.latin("۵۰"), "50")
        XCTAssertEqual(Digits.latin("رمز ١٢٣٤٥٦"), "رمز 123456")
    }

    func testCommasGroupThousandsAndTheDecimalMarksStartAFraction() {
        XCTAssertEqual(Digits.number("1,500"), 1500)
        XCTAssertEqual(Digits.number("١٬٢٠٠"), 1200)
        XCTAssertEqual(Digits.number("١٫٥"), 1.5)
        XCTAssertEqual(Digits.number("2.25"), 2.25)
        XCTAssertEqual(Digits.number(" ٢٥ "), 25)
        XCTAssertNil(Digits.number("خمسة"))
        XCTAssertNil(Digits.number(""))
    }

    func testWholeNumbers() {
        XCTAssertEqual(Digits.integer("٥٠"), 50)
        XCTAssertEqual(Digits.integer("1,000"), 1000)
        XCTAssertNil(Digits.integer("١٫٥"))
    }
}
