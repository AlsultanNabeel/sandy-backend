import XCTest
@testable import SandyApp

/// After a network change the screen judged success from the node it was opened with, an
/// old copy: a move that worked read as «rolled back».
final class NodeWiFiTests: XCTestCase {
    func testTheBoardCanBeChosenAgainAfterAFailedTry() {
        XCTAssertFalse(NodeWiFiView.boardLocked(during: .done(success: false)))
        XCTAssertFalse(NodeWiFiView.boardLocked(during: .idle))
        XCTAssertTrue(NodeWiFiView.boardLocked(during: .trying(secondsLeft: 5)))
    }
}
