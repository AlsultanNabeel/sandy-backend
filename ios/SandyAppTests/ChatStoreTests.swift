import XCTest
@testable import SandyApp

/// The chat store's sends (audit batch 11).
@MainActor
final class ChatStoreTests: XCTestCase {
    override func tearDown() {
        StubNetwork.uninstall()
        // The store keeps the open conversation per account; the tests have none.
        UserDefaults.standard.removeObject(forKey: "sandy_current_conv.")
    }

    private static let reply = Data("data: {\"reply\":\"تمام\",\"done\":true}\n\n".utf8)

    private func field(_ request: URLRequest, _ key: String) -> String? {
        let json = try? JSONSerialization.jsonObject(with: StubNetwork.body(of: request)) as? [String: Any]
        return json?[key] as? String
    }

    private func sent(_ path: String) -> [URLRequest] {
        StubNetwork.requests.filter { $0.url?.path.hasSuffix(path) == true }
    }

    /// The conversation list the store reloads after saving a reply.
    private var listReloads: Int {
        StubNetwork.requests.filter { $0.httpMethod == "GET" && $0.url?.path == "/api/conversations" }.count
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
        await settle { sent("/messages").count >= 3 && listReloads >= 1 }   // the line twice, the reply once

        XCTAssertEqual(store.messages.map(\.role), ["user", "sandy"])
        XCTAssertFalse(store.messages[0].failed)
        let sends = sent("/api/agent/stream").map { field($0, "client_msg_id") }
        XCTAssertEqual(sends.count, 2)
        XCTAssertEqual(sends[0], sends[1], "the retry went as another message")
        let lines = sent("/messages").filter { field($0, "role") == "user" }.map { field($0, "client_msg_id") }
        XCTAssertEqual(lines, [sends[0], sends[0]], "the line was saved again under another id")
    }

    /// M2: the streaming bubble's id was kept from the reply before, so «stop» before the first
    /// word of the next one sent that whole earlier reply as what was shown, and saved it again.
    func testStoppingBeforeTheFirstWordKeepsNothingOfTheReplyBefore() async {
        StubNetwork.install { request in
            guard request.url?.path == "/api/agent/stream" else { return (200, Data(#"{"ok":true}"#.utf8)) }
            return (200, Data("data: {\"text\":\"أ\"}\n\ndata: {\"reply\":\"أ\",\"done\":true}\n\n".utf8))
        }
        let api = TestClient.make()
        let store = ChatStore()
        _ = await store.send(api: api, text: "أول")
        await settle { sent("/messages").count >= 2 && listReloads >= 1 }

        StubNetwork.delay("POST", by: 1.0)                  // the next reply has not begun
        let second = Task { await store.send(api: api, text: "تاني") }
        try? await Task.sleep(nanoseconds: 200_000_000)
        store.stop(api: api)
        _ = await second.value
        await settle { !sent("/stop").isEmpty }

        XCTAssertEqual(sent("/stop").first.flatMap { field($0, "partial") }, "",
                       "the reply before was sent as what was shown")
        XCTAssertEqual(store.messages.map(\.text), ["أول", "أ", "تاني"])
        try? await Task.sleep(nanoseconds: 1_200_000_000)   // past the stop's answer
        XCTAssertEqual(sent("/messages").filter { field($0, "role") == "sandy" }.count, 1,
                       "the reply before was saved a second time")
    }
}
