import XCTest
@testable import SandyApp

/// The chat store's sends (audit batch 11).
@MainActor
final class ChatStoreTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    private static let reply = Data("data: {\"reply\":\"تمام\",\"done\":true}\n\n".utf8)

    private func field(_ request: URLRequest, _ key: String) -> String? {
        let json = try? JSONSerialization.jsonObject(with: StubNetwork.body(of: request)) as? [String: Any]
        return json?[key] as? String
    }

    private func sent(_ path: String) -> [URLRequest] {
        StubNetwork.requests.filter { $0.url?.path.hasSuffix(path) == true }
    }

    /// The store saves lines in the background; wait for them so none reaches the next test.
    private func settle(until done: () -> Bool) async {
        for _ in 0..<40 where !done() { try? await Task.sleep(nanoseconds: 50_000_000) }
    }

    /// F13 + M10: «أعد المحاولة» sent the line under a new id, so a turn the server had run
    /// (its reply lost on the way) ran again, and the line was added to the conversation twice.
    func testRetrySendsTheFailedLineAgainUnderItsOwnId() async throws {
        StubNetwork.install { request in
            guard request.url?.path == "/api/agent/stream" else { return (200, Data(#"{"ok":true}"#.utf8)) }
            let tries = StubNetwork.requests.filter { $0.url?.path == "/api/agent/stream" }.count
            return tries == 1 ? (500, Data(#"{"error":"internal_error"}"#.utf8)) : (200, Self.reply)
        }
        let api = TestClient.make()
        let store = ChatStore()
        let first = await store.send(api: api, text: "ذكريني بالدوا")
        XCTAssertNil(first)
        let failed = try XCTUnwrap(store.messages.first { $0.failed })

        let reply = await store.retry(api: api, failed)
        XCTAssertEqual(reply, "تمام")
        await settle { sent("/messages").count >= 3 }   // the line twice, the reply once

        XCTAssertEqual(store.messages.map(\.role), ["user", "sandy"])
        XCTAssertFalse(store.messages[0].failed)
        let sends = sent("/api/agent/stream").map { field($0, "client_msg_id") }
        XCTAssertEqual(sends.count, 2)
        XCTAssertEqual(sends[0], sends[1], "the retry went as another message")
        let lines = sent("/messages").filter { field($0, "role") == "user" }.map { field($0, "client_msg_id") }
        XCTAssertEqual(lines, [sends[0], sends[0]], "the line was saved again under another id")
    }
}
