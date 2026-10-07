import Foundation

/// What is left of a running session, read from its status the way the server advances it
/// (`focus_store.advance_focus_phase`): the phase now first, then each one after, with its end.
struct FocusPlan {
    struct Phase: Equatable {
        let isBreak: Bool
        /// 1-based.
        let cycle: Int
        let endsAt: Date
    }

    let phases: [Phase]

    init(_ status: FocusStatus, phaseEndsAt: Date) {
        var phase = Phase(isBreak: status.isBreak, cycle: status.cycleIdx, endsAt: phaseEndsAt)
        var out = [phase]
        // A focus phase of the last cycle ends the session; a break always leads to the next cycle.
        while phase.isBreak || phase.cycle < status.cycles {
            if !phase.isBreak && status.breakMin > 0 {
                phase = Phase(isBreak: true, cycle: phase.cycle,
                              endsAt: phase.endsAt.addingTimeInterval(TimeInterval(status.breakMin * 60)))
            } else {
                phase = Phase(isBreak: false, cycle: phase.cycle + 1,
                              endsAt: phase.endsAt.addingTimeInterval(TimeInterval(status.focusMin * 60)))
            }
            out.append(phase)
        }
        phases = out
    }
}

/// The focus screen's countdown: read from the phase's end on every tick, so time spent in
/// the background is not lost; at zero it asks the server once, and again only after
/// `retryAfter` when that failed (no network), never every second.
struct FocusClock {
    static let retryAfter: TimeInterval = 10

    var endsAt: Date?
    private var asking = false
    private var lastAsk = Date.distantPast

    init(endsAt: Date? = nil) { self.endsAt = endsAt }

    func remaining(at now: Date) -> Int {
        endsAt.map { max(0, Int($0.timeIntervalSince(now).rounded(.up))) } ?? 0
    }

    mutating func shouldRefresh(at now: Date) -> Bool {
        guard endsAt != nil, remaining(at: now) == 0, !asking,
              now.timeIntervalSince(lastAsk) >= Self.retryAfter else { return false }
        asking = true
        lastAsk = now
        return true
    }

    /// The ask came back (with a new end set, or failed).
    mutating func refreshed() { asking = false }
}
