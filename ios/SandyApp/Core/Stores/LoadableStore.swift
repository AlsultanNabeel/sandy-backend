import SwiftUI

/// Shared base for the feature list-stores.
///
/// Every `*Store` was re-declaring the same three pieces of view state — a
/// `loading` flag, a Sandy-voiced `notice` string, and a `demo` flag for the
/// signed-out placeholder data — and repeating the same localized-notice setter.
/// That lived in ~20 copies. It now lives here once. Subclasses add their own
/// `@Published` collection and domain methods; mutating those still publishes
/// through the inherited `objectWillChange`.
@MainActor
class LoadableStore: ObservableObject {
    /// A load/refresh is in flight.
    @Published var loading = false
    /// A gentle, Sandy-voiced message for the UI (empty = nothing to show).
    @Published var notice = ""
    /// Showing placeholder data because the user is signed out / has no data.
    @Published var demo = false

    /// Set `notice` to a localized string by key — the
    /// `LanguageManager.shared.s(...)` call every store repeated.
    func notify(_ key: String) {
        notice = LanguageManager.shared.s(key)
    }

    /// Clear any standing notice.
    func clearNotice() { notice = "" }
}
