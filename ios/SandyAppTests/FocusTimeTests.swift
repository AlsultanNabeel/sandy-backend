import XCTest
@testable import SandyApp

/// Audit batch nine: the focus timer and its lock-screen activity follow the clock.
@MainActor
final class FocusTimeTests: XCTestCase {
    private var fake: FakeScheduler!
    private var original: NotificationScheduler!

    override func setUp() async throws {
        try await super.setUp()
        original = NotificationManager.shared.center
        fake = FakeScheduler()
        NotificationManager.shared.center = fake
        NotificationManager.shared.sessionBegan()
    }

    override func tearDown() async throws {
        NotificationManager.shared.clearForSignOut()
        NotificationManager.shared.center = original
        try await super.tearDown()
    }

    private func status(_ phase: String, cycle: Int, of cycles: Int) -> FocusStatus {
        FocusStatus(active: true, phase: phase, cycleIdx: cycle, cycles: cycles,
                    focusMin: 25, breakMin: 5, remainingSec: 600, totalSec: 1500)
    }

    /// E4: what is left of a session, from its status: each phase with its end.
    func testThePlanRunsToTheSessionsEnd() {
        let end = Date().addingTimeInterval(600)
        let plan = FocusPlan(status("focus", cycle: 1, of: 2), phaseEndsAt: end)
        XCTAssertEqual(plan.phases.map(\.isBreak), [false, true, false])
        XCTAssertEqual(plan.phases.map(\.cycle), [1, 1, 2])
        XCTAssertEqual(plan.phases.map(\.endsAt), [end, end + 300, end + 1800])
        XCTAssertEqual(FocusPlan(status("focus", cycle: 2, of: 2), phaseEndsAt: end).phases.count, 1)
    }

    /// E4: the lock screen stopped at zero with the phone locked: every change of phase now
    /// rings at its time, so a locked phone still hears the break, the next round and the end.
    func testEveryPhaseChangeRingsWithThePhoneLocked() {
        let end = Date().addingTimeInterval(600)
        NotificationManager.shared.scheduleFocus(FocusPlan(status("focus", cycle: 1, of: 2), phaseEndsAt: end))
        XCTAssertEqual(fake.ids("focus.").count, 3)
        NotificationManager.shared.scheduleFocus(nil)
        XCTAssertEqual(fake.ids("focus.").count, 0, "an ended session still rang")
    }
}
