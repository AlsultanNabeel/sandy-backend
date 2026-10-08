import XCTest
@testable import SandyApp

/// The month My Life adds the phone's new entries to is the server's (Gregorian) month,
/// whatever calendar the phone shows: under a Hijri calendar an expense from the start of
/// this Gregorian month was left out of «this month's spending».
final class LifeStatsMonthTests: XCTestCase {
    func testThisMonthIsTheGregorianMonthOnAHijriPhone() throws {
        var hijri = Calendar(identifier: .islamicUmmAlQura)
        hijri.timeZone = try XCTUnwrap(TimeZone(identifier: "Asia/Riyadh"))
        var greg = Calendar(identifier: .gregorian)
        greg.timeZone = hijri.timeZone
        // 25 Oct 2026; 2 Oct 2026 is in the same Gregorian month and the previous Hijri one.
        let now = try XCTUnwrap(greg.date(from: DateComponents(year: 2026, month: 10, day: 25, hour: 12)))
        let early = try XCTUnwrap(greg.date(from: DateComponents(year: 2026, month: 10, day: 2, hour: 12)))
        XCTAssertNotEqual(hijri.component(.month, from: now), hijri.component(.month, from: early),
                          "the dates must straddle a Hijri month for this test to mean anything")

        let iso = ISO8601DateFormatter()
        let entry = try JSONDecoder().decode(LogEntry.self, from: Data("""
            {"id":"e1","kind":"expense","text":"قهوة","at":"\(iso.string(from: early))","data":{"amount":5}}
            """.utf8))
        let stats = LifeStats(days: Array(repeating: 0, count: 30), spent: 0, habits: 0, logged: 0)
        let out = stats.including([entry], now: now, calendar: hijri)
        XCTAssertEqual(out.spent, 5)
    }
}
