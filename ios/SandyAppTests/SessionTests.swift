import XCTest
@testable import SandyApp

/// Audit batch three: the session, sign-out and switching accounts.
@MainActor
final class SessionTests: XCTestCase {
    override func tearDown() {
        StubNetwork.uninstall()
        super.tearDown()
    }

    /// K1: the server renews a day-old token; a week in, the user was signed out instead.
    func testARenewedTokenIsKept() async throws {
        let api = TestClient.make()
        api.token = "old"
        StubNetwork.install(status: 200, json: "[]")
        StubURLProtocol.headers = [APIClient.renewedHeader: "new"]
        _ = try? await api.getFeatures()
        XCTAssertEqual(api.token, "new")
    }

    /// K1: a renewal for a request sent before a sign-out or a switch is not taken.
    func testARenewalForAnotherSessionIsNotTaken() {
        let api = TestClient.make()
        api.token = "second"
        let resp = HTTPURLResponse(url: URL(string: "https://example.test")!, statusCode: 200,
                                   httpVersion: nil, headerFields: [APIClient.renewedHeader: "first-renewed"])!
        api.keepRenewed(resp, sent: "first")
        XCTAssertEqual(api.token, "second")
        api.token = nil
        api.keepRenewed(resp, sent: "first")
        XCTAssertNil(api.token, "a renewal signed a signed-out phone back in")
    }

    /// An unsigned token for `uid`: the client reads the account from it, never checks it.
    static func token(_ uid: String) -> String {
        func b64url(_ s: String) -> String {
            Data(s.utf8).base64EncodedString().replacingOccurrences(of: "+", with: "-")
                .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        }
        return "\(b64url("{\"alg\":\"HS256\"}")).\(b64url("{\"user_id\":\"\(uid)\"}")).sig"
    }

    /// Waits for the cache's serial queue to write what was queued before.
    private func settle(_ check: () -> Bool) async {
        for _ in 0..<50 where !check() { try? await Task.sleep(nanoseconds: 20_000_000) }
    }

    private func sentWrites() -> Int {
        StubNetwork.requests.filter { $0.url?.path == "/api/items" && $0.httpMethod == "POST" }.count
    }

    /// K1: the session ended with a change still unsent: it waits for its own account,
    /// is never sent for another one, and is not wiped by the sign-out.
    func testAnEndedSessionKeepsItsUnsentChangeForItsOwnerOnly() async throws {
        let owner = "owner-\(UUID().uuidString.prefix(8))", other = "other-\(UUID().uuidString.prefix(8))"
        let api = TestClient.make()
        api.token = Self.token(owner)
        StubNetwork.install(status: StubNetwork.offline, json: "{}")
        try await Outbox.shared.send(api, "/api/items", method: "POST", body: ["text": "حليب"])
        XCTAssertEqual(Outbox.shared.count, 1)

        // The session ends by itself: the token goes, the caches go, the outbox stays.
        api.token = nil
        DiskCache.clearAll(except: Outbox.fileKey)
        await settle { DiskCache.load([Outbox.Op].self, key: Outbox.fileKey, userId: owner)?.count == 1 }
        XCTAssertEqual(DiskCache.load([Outbox.Op].self, key: Outbox.fileKey, userId: owner)?.count, 1,
                       "signing out wiped the change made offline")

        StubNetwork.install(status: 200, json: "{}")
        await Outbox.shared.drain(api)
        XCTAssertEqual(sentWrites(), 0, "sent with no one signed in")
        api.token = Self.token(other)
        await Outbox.shared.drain(api)
        XCTAssertEqual(sentWrites(), 0, "another account sent it")
        api.token = Self.token(owner)
        await Outbox.shared.drain(api)
        XCTAssertEqual(sentWrites(), 1, "the owner's change never went out")
        XCTAssertTrue(Outbox.shared.isEmpty)
    }

    /// K5: «reset my data» wiped the server only; the outbox then sent the old changes and
    /// brought rows back. It is dropped before the reset, not sent.
    func testTheOutboxIsDroppedNotSentBeforeAReset() async throws {
        let owner = "reset-\(UUID().uuidString.prefix(8))"
        let api = TestClient.make()
        api.token = Self.token(owner)
        StubNetwork.install(status: StubNetwork.offline, json: "{}")
        try await Outbox.shared.send(api, "/api/items", method: "POST", body: ["text": "حليب"])
        Outbox.shared.discard()
        await settle { DiskCache.load([Outbox.Op].self, key: Outbox.fileKey, userId: owner)?.isEmpty == true }
        XCTAssertEqual(DiskCache.load([Outbox.Op].self, key: Outbox.fileKey, userId: owner)?.count, 0)
        StubNetwork.install(status: 200, json: "{}")
        await Outbox.shared.drain(api)
        XCTAssertEqual(sentWrites(), 0, "a change from before the reset was sent after it")
    }

    /// A write with no one signed in is refused, not queued: it used to bind the outbox to
    /// no account, and the next drain reloaded and sent what had just been dropped.
    func testAWriteWithNoOneSignedInIsNotQueued() async {
        let api = TestClient.make()
        StubNetwork.install(status: 200, json: "{}")
        do {
            try await Outbox.shared.send(api, "/api/items", method: "POST", body: ["text": "حليب"])
            XCTFail("queued with no one signed in")
        } catch {
            XCTAssertEqual((error as? APIError)?.kind, .unauthorized)
        }
        XCTAssertEqual(sentWrites(), 0)
    }

    /// K3: My Life's numbers live in a shared store; the next account on the phone saw them.
    func testMyLifeNumbersDoNotOutliveTheSession() throws {
        StubNetwork.install(status: 200, json: "{}")
        let entry = try JSONDecoder().decode(LogEntry.self, from: Data("""
            {"id":"e1","kind":"expense","text":"قهوة","at":"\(ISO8601DateFormatter().string(from: Date()))","data":{"amount":7}}
            """.utf8))
        LogStore.noteMade(entry)
        LifeStatsStore.shared.setBudget(api: TestClient.make(), 500)
        XCTAssertEqual(LifeStatsStore.shared.stats.spent, 7)
        SessionReset.clearShared()
        XCTAssertEqual(LifeStatsStore.shared.stats.spent, 0, "the last account's spending showed")
        XCTAssertEqual(LifeStatsStore.shared.stats.budget ?? 0, 0, "the last account's budget showed")
    }

    /// K4: a list still loading when the account left (signed out, or switched to another)
    /// came back and showed, cached and published the old account's rows.
    func testALateReplyAfterASwitchShowsAndSavesNothing() async throws {
        let first = "first-\(UUID().uuidString.prefix(8))"
        let api = TestClient.make()
        api.token = Self.token(first)
        StubNetwork.install(status: 200, json: """
            {"items":[{"id":"t1","list":"tasks","text":"مهمة الحساب الأول","done":false}]}
            """)
        StubNetwork.delay("GET", by: 0.4)
        let store = ItemsStore(list: "tasks")
        let loading = Task { await store.load(api: api) }
        try await Task.sleep(nanoseconds: 100_000_000)
        AccountSession.next()
        api.token = Self.token("second")
        await loading.value
        XCTAssertTrue(store.items.isEmpty, "the first account's tasks showed for the second")
        store.items = []
        await settle { false }
        XCTAssertNil(DiskCache.load([ListItem].self, key: "items.tasks.open", userId: first),
                     "the store from before the switch still wrote its cache")
    }

    /// S1: after sign-out the morning and evening nudges still had the last account's open
    /// tasks and habit names, and coming back to the front scheduled them again.
    func testNudgesForgetTheAccountAndWaitForTheNextSession() throws {
        let notes = NotificationManager.shared
        notes.sessionBegan()
        notes.setOpenTasks(3)
        notes.setHabits(left: ["ركض"], total: 1)
        XCTAssertEqual(notes.nudgeInputs()?.habitsLeft, ["ركض"])
        notes.clearForSignOut()
        notes.setHabits(left: ["ركض"], total: 1)
        XCTAssertNil(notes.nudgeInputs(), "nudges were built with no one signed in")
        notes.sessionBegan()
        let fresh = try XCTUnwrap(notes.nudgeInputs())
        XCTAssertEqual(fresh.tasks, 0)
        XCTAssertEqual(fresh.habitsLeft, [], "the last account's habit names reached the next one")
    }

    /// M1: a minimised call went on after sign-out, the mic sending as the old account.
    func testSignOutEndsTheCall() {
        let call = GeminiLiveManager.shared
        call.phase = .listening
        SessionReset.clearShared()
        XCTAssertEqual(call.phase, .idle, "the call outlived the session")
        XCTAssertFalse(call.inCall)
    }

    /// A7: the focus Live Activity stayed after sign-out, and its «stop» went out with the
    /// next account's token.
    func testAFocusStopWithNoActivityUpSendsNothing() async throws {
        StubNetwork.install(status: 200, json: "{}")
        SessionReset.clearShared()
        FocusLiveActivity.shared.stopFromLink()
        try await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertTrue(StubNetwork.requests.isEmpty, "a stale focus stop reached the server")
    }

    /// K7: a delete still offered for «تراجع» at sign-out stayed up and was sent with the
    /// next account's token; now it goes first, within a short limit, or is dropped.
    func testAPendingUndoIsSentBeforeSignOutWithinALimitAndNeverAfter() async {
        let undo = UndoCenter.shared
        var sent = 0
        undo.offer("حذفت", icon: "trash", undo: {}, commit: { sent += 1 })
        await undo.commitBeforeSignOut()
        XCTAssertEqual(sent, 1, "the pending delete never went out")

        undo.offer("حذفت", icon: "trash", undo: {}, commit: { try? await Task.sleep(for: .seconds(10)) })
        let began = Date()
        await undo.commitBeforeSignOut(limit: .milliseconds(200))
        XCTAssertLessThan(Date().timeIntervalSince(began), 2, "no network held the sign-out up")

        undo.offer("حذفت", icon: "trash", undo: {}, commit: { sent += 1 })
        SessionReset.clearShared()
        undo.commitNow()
        await Task.yield()
        XCTAssertEqual(sent, 1, "the offer outlived the session and went out as the next account")
    }

    /// K6: «talk to Sandy» tapped while signed out waited with no time, and the call (and
    /// the mic) opened by itself minutes later once sign-in was done.
    func testACallLinkWaitsAMinuteAtMostAndNotAcrossASignOut() {
        let router = DeepLinkRouter.shared
        router.ask(.call)
        XCTAssertNil(router.take(now: Date().addingTimeInterval(DeepLinkRouter.pendingLife + 1)),
                     "a call link opened minutes after it was tapped")
        router.ask(.call)
        SessionReset.clearShared()
        XCTAssertNil(router.take(), "a call link outlived the sign-out")
        router.ask(.chat)
        XCTAssertEqual(router.take(), .chat)
        XCTAssertNil(router.take(), "a link is taken once")
    }

    /// S7: notification settings were pulled only when their screen opened, a change saved
    /// offline was lost and overwritten by the server's copy, and sign-out kept them for the
    /// next account.
    func testNotificationSettingsSurviveOfflineAndFollowTheAccount() async {
        let api = TestClient.make()
        api.token = Self.token("prefs")
        var quiet = NotificationPrefs()
        quiet.quietStart = "22:00"
        quiet.quietEnd = "07:00"
        StubNetwork.install(status: StubNetwork.offline, json: "{}")
        await NotificationPrefs.change(to: quiet, api: api)
        XCTAssertTrue(NotificationPrefs.unsent)

        // Back online, the server still has the old copy: ours goes up, theirs does not win.
        StubNetwork.install(status: 200, json: #"{"reminders":true,"daily":true,"proactive":true,"quiet_start":"","quiet_end":""}"#)
        await NotificationPrefs.pull(api: api)
        XCTAssertEqual(NotificationPrefs.current.quietStart, "22:00", "the offline change was overwritten")
        XCTAssertFalse(NotificationPrefs.unsent)
        XCTAssertTrue(StubNetwork.requests.contains { $0.httpMethod == "POST" })

        // A pull with nothing unsent takes the server's copy (another phone, a reinstall).
        await NotificationPrefs.pull(api: api)
        XCTAssertEqual(NotificationPrefs.current.quietStart, "")

        quiet.save()
        SessionReset.clearShared()
        XCTAssertEqual(NotificationPrefs.current, NotificationPrefs(), "the last account's settings stayed")
    }
}
