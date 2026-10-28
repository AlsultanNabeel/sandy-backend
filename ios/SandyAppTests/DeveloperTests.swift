import XCTest
@testable import SandyApp

/// Phase zero: switching between production and staging never mixes their sessions, the
/// developer screen follows the server's switches, and the owner's trace and cost pages
/// read what the server sends.
@MainActor
final class DeveloperTests: XCTestCase {
    override func tearDown() {
        StubNetwork.uninstall()
        super.tearDown()
    }

    func testEachServerKeepsItsOwnSignIn() {
        let store = MemoryTokenStore()
        let api = APIClient(baseURL: Backend.Server.production.url, tokenStore: store,
                            mirrorsShared: false)
        api.token = "prod-token"
        api.switchServer(to: .staging)
        XCTAssertEqual(api.baseURL, Backend.Server.staging.url)
        XCTAssertNil(api.token, "staging started signed in as production")
        api.token = "staging-token"
        api.switchServer(to: .production)
        XCTAssertEqual(api.token, "prod-token")
        api.switchServer(to: .staging)
        XCTAssertEqual(api.token, "staging-token")
    }

    func testSwitchingToTheServerItIsOnChangesNothing() {
        let api = APIClient(baseURL: Backend.Server.production.url, tokenStore: MemoryTokenStore(),
                            mirrorsShared: false)
        api.token = "prod-token"
        api.switchServer(to: .production)
        XCTAssertEqual(api.token, "prod-token")
    }

    func testAnAddressIsKnownAsItsServer() {
        XCTAssertEqual(Backend.Server(url: Backend.Server.staging.url), .staging)
        XCTAssertEqual(Backend.Server(url: Backend.Server.production.url + "/"), .production)
        XCTAssertEqual(Backend.Server(url: "http://nabeelsul.local:8080"), .production)
    }

    func testTheServersSwitchesAreRead() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: #"{"hidden": ["weather"], "on": ["dev_tools"]}"#)
        let f = try await api.getFeatures()
        XCTAssertEqual(f.hidden, ["weather"])
        XCTAssertEqual(f.on, ["dev_tools"])
    }

    func testAnOlderServerWithoutSwitchesIsRead() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: #"{"hidden": []}"#)
        let f = try await api.getFeatures()
        XCTAssertEqual(f.on, [])
    }

    func testTheDeveloperScreenShowsForTheSwitchOrOnStaging() {
        XCTAssertTrue(DeveloperAccess.shows(on: ["dev_tools"], server: .production))
        XCTAssertTrue(DeveloperAccess.shows(on: [], server: .staging))
        XCTAssertFalse(DeveloperAccess.shows(on: ["tasks"], server: .production))
    }

    func testTheTraceListIsRead() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: """
        {"traces": [{"_id": "t1", "user_id": "u1", "at": "2026-10-28T10:00:00+00:00",
          "source": "chat", "thread_id": "c1", "routed_by": "brain",
          "tools": [{"name": "list_add", "ok": true, "ms": 12}],
          "model_calls": [{"provider": "azure", "model": "gpt-4.1", "tokens_in": 900,
                           "tokens_out": 40, "tokens_cached": 0, "ms": 800}],
          "tokens_in": 900, "tokens_out": 40, "cost_usd": 0.00212, "ms_total": 1500,
          "skills": [], "task_id": null, "error": null, "encrypted": true}]}
        """)
        let rows = try await api.ownerTraces()
        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows[0].id, "t1")
        XCTAssertEqual(rows[0].tools.map(\.name), ["list_add"])
        XCTAssertEqual(rows[0].tokensIn, 900)
        XCTAssertEqual(rows[0].costUsd, 0.00212, accuracy: 1e-9)
        XCTAssertEqual(StubNetwork.requests.last?.url?.path, "/api/owner/traces")
    }

    func testOneTurnIsReadWithItsWords() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: """
        {"_id": "t1", "user_id": "u1", "at": "2026-10-28T10:00:00+00:00", "source": "voice",
         "thread_id": "voice", "routed_by": "voice", "request": "ضيفي حليب", "reply": "ضفت",
         "tools": [{"name": "list_add", "ok": true, "ms": 12,
                    "args": {"list": "shopping", "text": "حليب"}, "result": {"ok": true}}],
         "model_calls": [], "tokens_in": 0, "tokens_out": 0, "cost_usd": 0, "ms_total": 3,
         "skills": [], "task_id": null, "error": null, "encrypted": true}
        """)
        let t = try await api.ownerTrace(id: "t1")
        XCTAssertEqual(t.request, "ضيفي حليب")
        XCTAssertEqual(t.reply, "ضفت")
        XCTAssertTrue(t.tools[0].args?.contains("shopping") ?? false)
        XCTAssertEqual(t.tools[0].result, "{\"ok\":true}")
    }

    func testAnotherUsersTurnHasNoWords() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: """
        {"_id": "t2", "user_id": "u2", "at": "2026-10-28T10:00:00+00:00", "source": "chat",
         "thread_id": "c", "routed_by": "brain", "request": null, "reply": null,
         "tools": [{"name": "weather", "ok": true, "ms": 5, "args": null, "result": null}],
         "model_calls": [], "tokens_in": 10, "tokens_out": 1, "cost_usd": 0, "ms_total": 3,
         "skills": [], "task_id": null, "error": null, "encrypted": true}
        """)
        let t = try await api.ownerTrace(id: "t2")
        XCTAssertNil(t.request)
        XCTAssertNil(t.tools[0].args)
    }

    func testTheCostsAreRead() async throws {
        let api = TestClient.make()
        StubNetwork.install(json: """
        {"days": 30, "total_usd": 1.25,
         "by_user": [{"user_id": "u1", "label": "نبيل", "turns": 40, "tokens_in": 9000,
                      "tokens_out": 700, "usd": 1.0}],
         "by_source": [{"source": "chat", "turns": 30, "usd": 0.9}], "by_task": []}
        """)
        let c = try await api.ownerCosts(days: 30)
        XCTAssertEqual(c.totalUsd, 1.25, accuracy: 1e-9)
        XCTAssertEqual(c.byUser.first?.label, "نبيل")
        XCTAssertEqual(c.bySource.first?.turns, 30)
        XCTAssertEqual(StubNetwork.requests.last?.url?.query, "days=30")
    }
}
