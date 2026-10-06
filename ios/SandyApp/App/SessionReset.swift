import Foundation

/// What the phone keeps for the signed-in account in memory, outside its cache files,
/// wiped in one place when the session ends (`AppState.signOut`), so the next account on
/// this phone inherits none of it.
@MainActor
enum SessionReset {
    static func clearShared() {
        LifeStatsStore.shared.reset()
        LogStore.forgetMade()
    }
}
