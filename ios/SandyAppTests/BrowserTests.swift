import XCTest
@testable import SandyApp

/// Phase seven: the browser's screens behind the `browser` switch: the sites and their level,
/// «طلّعها», «Sandy's browser», the emergency stop, and the links in Sandy's replies.
@MainActor
final class BrowserTests: XCTestCase {
    override func tearDown() {
        StubNetwork.uninstall()
        super.tearDown()
    }

    private func paths() -> [String] {
        StubNetwork.requests.map { "\($0.httpMethod ?? "") \($0.url?.path ?? "")" }
    }

    func testTheScreenShowsOnlyWithTheSwitch() {
        XCTAssertTrue(BrowserAccess.shows(on: ["browser"]))
        XCTAssertFalse(BrowserAccess.shows(on: ["tasks"]))
    }

    func testTheSitesAreRead() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: """
        {"sites": [{"site": "forms.example.com", "level": "submit", "signed_in": true,
          "session_at": "2026-11-02T10:00:00+00:00"}]}
        """)
        let rows = try await api.browserSites()
        XCTAssertEqual(rows.map(\.site), ["forms.example.com"])
        XCTAssertEqual(rows[0].level, BrowserSite.submit)
        XCTAssertTrue(rows[0].signedIn)
        XCTAssertEqual(paths(), ["GET /api/browser/sites"])
    }

    func testSigningOutAndTheStopGoToTheirRoutes() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: """
        {"site": {"site": "forms.example.com", "level": "read", "signed_in": false, "session_at": null},
         "stopped": true}
        """)
        _ = try await api.signOutBrowserSite(site: "forms.example.com")
        let stopped = try await api.setStopped(true)
        XCTAssertTrue(stopped)
        XCTAssertEqual(paths(), ["DELETE /api/browser/sites/forms.example.com/session", "POST /api/stop"])
    }

    func testTheLinksInHerRepliesOpenTheBrowsersScreens() {
        let router = DeepLinkRouter.shared
        XCTAssertTrue(router.handle(URL(string: "sandy://browser/login?url=https%3A%2F%2Fshop.example%2Forders")!))
        XCTAssertEqual(router.take(), .browserLogin(URL(string: "https://shop.example/orders")!))
        XCTAssertTrue(router.handle(URL(string: "sandy://browser/live?job=j1")!))
        XCTAssertEqual(router.take(), .browserLive("j1"))
        // A sign-in link to anything but a web page opens nothing.
        router.handle(URL(string: "sandy://browser/login?url=file%3A%2F%2F%2Fetc")!)
        XCTAssertNil(router.take())
    }

    func testHerLinksAreTappableInAReply() {
        let shown = Linked.text("سجّل من هون: sandy://browser/login?url=x وبعدين https://example.com")
        let links = shown.runs.compactMap(\.link).map(\.absoluteString)
        XCTAssertEqual(links.sorted(), ["https://example.com", "sandy://browser/login?url=x"])
    }

    /// 13 Nov: the question came while he watched the fill and never showed there. The view reads
    /// the question it waits on, and his answer from it goes into the fill's conversation on the
    /// chat's own path: his line, the turn under that same id, her reply.
    func testTheLiveViewReadsTheQuestionAndAnswersItOnTheChatsPath() async throws {
        let api = TestClient.make()
        StubNetwork.install { request in
            switch request.url?.path ?? "" {
            case "/api/browser/jobs/j1":
                return (200, Data(#"{"id":"j1","site":"httpbin.org","status":"held","open":true,"thread":"c2","#
                    .utf8) + Data(#""ask":{"kind":"confirm","text":"متأكد إنك بدك أبعت؟ (اه/لأ)"}}"#.utf8))
            case "/api/agent/stream":
                return (200, Data("data: {\"reply\":\"انبعت ✅\",\"done\":true}\n\n".utf8))
            default:
                return (200, Data("{}".utf8))
            }
        }
        let job = try await api.browserJob(job: "j1")
        XCTAssertEqual(job.ask, BrowserJobView.Ask(kind: "confirm", text: "متأكد إنك بدك أبعت؟ (اه/لأ)"))
        XCTAssertEqual(job.thread, "c2")
        let said = await api.say("اه", in: "c2")
        XCTAssertEqual(said?.reply, "انبعت ✅")
        XCTAssertEqual(paths().suffix(3), ["POST /api/conversations/c2/messages", "POST /api/agent/stream",
                                           "POST /api/conversations/c2/messages"])
        let bodies = StubNetwork.requests.suffix(3).map {
            (try? JSONSerialization.jsonObject(with: StubNetwork.body(of: $0))) as? [String: Any] ?? [:]
        }
        XCTAssertEqual(bodies[0]["role"] as? String, "user")
        XCTAssertEqual(bodies[1]["conversation_id"] as? String, "c2")
        XCTAssertEqual(bodies[0]["client_msg_id"] as? String, bodies[1]["client_msg_id"] as? String)
        XCTAssertEqual(bodies[2]["text"] as? String, "انبعت ✅")
    }
}
