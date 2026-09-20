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
    /// آخر جلب فشل بسبب الاتصال، والشاشة بتعرض النسخة المحفوظة (`OfflineBanner`).
    @Published var offline = false
    /// في محتوى معروض (من الكاش أو من جلب ناجح) — فخطأ اتصال بيصير «بدون إنترنت»
    /// بدل رسالة خطأ.
    var hasSnapshot = false

    /// Monotonic token for the latest load. A load that was cancelled and
    /// replaced must not clear the spinner (or write results) of the load that
    /// replaced it — only the current generation may.
    private var loadGeneration = 0

    /// Start a new load: bumps the generation, shows the spinner, and returns
    /// the token the load passes to `isCurrentLoad` / `endLoad`.
    func beginLoad() -> Int {
        loadGeneration += 1
        loading = true
        return loadGeneration
    }

    /// True while `generation` is still the most recent load.
    func isCurrentLoad(_ generation: Int) -> Bool {
        generation == loadGeneration
    }

    /// Finish a load: clears `loading` only if no newer load has started.
    func endLoad(_ generation: Int) {
        if generation == loadGeneration { loading = false }
    }

    /// Set `notice` to a localized string by key — the
    /// `LanguageManager.shared.s(...)` call every store repeated.
    func notify(_ key: String) {
        notice = LanguageManager.shared.s(key)
    }

    /// Clear any standing notice.
    func clearNotice() { notice = "" }

    // MARK: - وضع بدون إنترنت

    /// الخطأ انقطاع اتصال (مش رد من الخادم) — `APIClient` بيحوّل أخطاء الشبكة لـ`.connection`.
    static func isConnectionError(_ error: Error) -> Bool {
        (error as? APIError)?.kind == .connection || error is URLError
    }

    /// جلب نجح: المعروض صار حيّ.
    func markLoaded() {
        hasSnapshot = true
        offline = false
    }

    /// جلب فشل: الإلغاء والجلب القديم بيتجاهلوا؛ انقطاع اتصال ومعنا محتوى → `offline`
    /// ونخلّي النسخة المعروضة؛ غير هيك → `fallback` (رسالة الخطأ المعتادة للستور).
    func failLoad(_ error: Error, generation: Int, fallback: () -> Void) {
        guard !error.isCancellation, isCurrentLoad(generation) else { return }
        if hasSnapshot && Self.isConnectionError(error) {
            offline = true
        } else {
            offline = false
            fallback()
        }
    }

    /// Run an optimistic mutation: `apply` updates local state immediately for a
    /// snappy UI, `call` reconciles with the backend in the background, and on
    /// failure `rollback` restores the previous state and a localized `noticeKey`
    /// is shown. Removes the `Task { do/catch { rollback; notify } }` scaffolding
    /// every fire-and-forget mutation (delete / toggle / reorder) was repeating.
    func optimistic(
        _ noticeKey: String,
        apply: () -> Void,
        rollback: @escaping () -> Void,
        call: @escaping () async throws -> Void
    ) {
        apply()
        Task { @MainActor in
            do {
                try await call()
            } catch {
                rollback()
                self.notify(noticeKey)
            }
        }
    }
}
