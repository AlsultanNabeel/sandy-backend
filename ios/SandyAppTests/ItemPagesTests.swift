import XCTest
@testable import SandyApp

/// A list longer than one page (100 rows) used to stop at the first page; the project
/// lists came from the 500 oldest rows.
final class ItemPagesTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    private func rows(_ range: Range<Int>) -> String {
        range.map { #"{"id":"r\#($0)","list":"tasks","text":"t\#($0)","done":false}"# }
            .joined(separator: ",")
    }

    func testAnOpenListFollowsEveryPage() async throws {
        StubNetwork.install { request in
            let cursor = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?
                .queryItems?.first { $0.name == "cursor" }?.value
            if cursor == nil {
                return (200, Data(#"{"items":[\#(self.rows(0..<100))],"next":"c1"}"#.utf8))
            }
            return (200, Data(#"{"items":[\#(self.rows(100..<150))]}"#.utf8))
        }
        let items = try await TestClient.make().listItems("tasks", done: false)
        XCTAssertEqual(items.count, 150)
        XCTAssertEqual(StubNetwork.requests.count, 2)
    }

    func testTheDoneHalfIsOnePageOfTheNewest() async throws {
        StubNetwork.install(json: #"{"items":[\#(rows(0..<100))],"next":"c1"}"#)
        let items = try await TestClient.make().listItems("tasks", done: true)
        XCTAssertEqual(items.count, 100)
        XCTAssertEqual(StubNetwork.requests.count, 1)
    }

    func testProjectListsComeFromEveryListName() async throws {
        StubNetwork.install(json: #"{"lists":["tasks","project:بيت","project:شغل"]}"#)
        let names = try await TestClient.make().projectLists()
        XCTAssertEqual(names, ["project:بيت", "project:شغل"])
        XCTAssertEqual(StubNetwork.requests.first?.url?.path, "/api/items/lists")
    }
}
