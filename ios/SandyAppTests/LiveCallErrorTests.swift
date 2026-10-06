import XCTest
@testable import SandyApp

/// The server ends a call by itself (nobody talking, or the maximum length). The call
/// screen used to print the raw code it sent.
@MainActor
final class LiveCallErrorTests: XCTestCase {
    func testTheServerEndingTheCallReadsAsASentence() {
        for code in ["call_idle", "call_time_limit", "call_minutes_exceeded"] {
            let line = GeminiLiveManager.errorLine(code)
            XCTAssertNotEqual(line, code)
            XCTAssertFalse(line.contains("_"), "\(code) shows as a code: \(line)")
        }
    }
}
