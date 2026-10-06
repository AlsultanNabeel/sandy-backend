import XCTest
@testable import SandyApp

/// A remote stream that stopped (the camera went off, the stream timed out) kept its last
/// picture on screen for ever, looking live. Ten seconds with no new frame says it stopped.
final class StreamWatchTests: XCTestCase {
    func testTenSecondsWithoutAFrameIsAStoppedStream() {
        let last = Date(timeIntervalSince1970: 1000)
        XCTAssertFalse(StreamWatch.stalled(lastFrameAt: last, now: last.addingTimeInterval(9)))
        XCTAssertTrue(StreamWatch.stalled(lastFrameAt: last, now: last.addingTimeInterval(11)))
        XCTAssertFalse(StreamWatch.stalled(lastFrameAt: nil, now: last), "no frame yet is another case")
    }
}
