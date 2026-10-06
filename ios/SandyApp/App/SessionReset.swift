import Foundation

/// Which signed-in session this is. It moves on every sign-in and sign-out, so work begun
/// under an earlier one (a load still on its way, a store from before a switch) can tell
/// that its account is gone and show, save and publish nothing.
@MainActor
enum AccountSession {
    private(set) static var generation = 0
    static func next() { generation &+= 1 }
}

/// What the phone keeps for the signed-in account in memory, outside its cache files,
/// wiped in one place when the session ends (`AppState.signOut`), so the next account on
/// this phone inherits none of it.
@MainActor
enum SessionReset {
    static func clearShared() {
        ItemsStore.cancelLoads()
        LifeStatsStore.shared.reset()
        LogStore.forgetMade()
    }
}
