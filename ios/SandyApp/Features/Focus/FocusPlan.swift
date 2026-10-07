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
