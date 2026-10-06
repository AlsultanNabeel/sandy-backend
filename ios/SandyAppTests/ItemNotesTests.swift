import XCTest
@testable import SandyApp

/// A link shared as a task lands in its notes («اقرا: example.com» with the address there);
/// the notes were never read by the app, so the link was nowhere to be seen.
final class ItemNotesTests: XCTestCase {
    private func item(_ data: String) throws -> ListItem {
        try JSONDecoder().decode(ListItem.self, from: Data("""
            {"id":"i1","list":"tasks","text":"اقرا: example.com","done":false,"data":\(data)}
            """.utf8))
    }

    func testATaskShowsItsNotesWithTheLinkInThem() throws {
        let task = try item(#"{"notes":"https://example.com/a?b=1"}"#)
        XCTAssertEqual(task.notes, "https://example.com/a?b=1")
        XCTAssertEqual(task.notesShown?.runs.compactMap(\.link).first,
                       URL(string: "https://example.com/a?b=1"))
    }

    func testNoNotesIsNil() throws {
        XCTAssertNil(try item("{}").notes)
        XCTAssertNil(try item(#"{"notes":"  "}"#).notes)
    }

    func testEditedNotesGoInTheDataAndEmptyOnesLeave() {
        let kept: [String: JSONValue] = ["repeat": .string("daily"), "notes": .string("قديم")]
        let set = ItemDraft(text: "x", due: nil, important: false, notes: "جديد")
        XCTAssertEqual(ItemDraft.notes(set, into: kept)["notes"], .string("جديد"))
        XCTAssertEqual(ItemDraft.notes(set, into: kept)["repeat"], .string("daily"))
        let cleared = ItemDraft(text: "x", due: nil, important: false, notes: "")
        XCTAssertNil(ItemDraft.notes(cleared, into: kept)["notes"])
        let untouched = ItemDraft(text: "x", due: nil, important: false)
        XCTAssertEqual(ItemDraft.notes(untouched, into: kept)["notes"], .string("قديم"))
    }
}
