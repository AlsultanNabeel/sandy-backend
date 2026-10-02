import SwiftUI

/// Shared `loading` / `notice` / `demo` state for the feature list-stores.
@MainActor
class LoadableStore: ObservableObject {
    @Published var loading = false
    /// Sandy-voiced message for the UI (empty = nothing to show).
    @Published var notice = ""
    /// Placeholder data because the user is signed out / has no data.
    @Published var demo = false
    /// آخر جلب فشل بالاتصال والشاشة بتعرض النسخة المحفوظة.
    @Published var offline = false
    /// في محتوى معروض، فخطأ اتصال بيصير «بدون إنترنت» بدل رسالة خطأ.
    var hasSnapshot = false

    /// A cancelled-and-replaced load must not clear the spinner of the load that replaced it.
    private var loadGeneration = 0

    /// Bumps the generation, shows the spinner, returns the load's token.
    func beginLoad() -> Int {
        loadGeneration += 1
        loading = true
        return loadGeneration
    }

    func isCurrentLoad(_ generation: Int) -> Bool {
        generation == loadGeneration
    }

    /// Clears `loading` only if no newer load has started.
    func endLoad(_ generation: Int) {
        if generation == loadGeneration { loading = false }
    }

    func notify(_ key: String) {
        notice = LanguageManager.shared.s(key)
    }

    func clearNotice() { notice = "" }


    static func isConnectionError(_ error: Error) -> Bool {
        (error as? APIError)?.kind == .connection || error is URLError
    }

    /// The last saved copy, shown before the first fetch so a tab opens on it offline.
    func restoreSnapshot<T: Decodable>(_ type: T.Type, key: String, api: APIClient, _ show: (T) -> Void) {
        guard !hasSnapshot, let cached = DiskCache.load(type, key: key, userId: api.currentUserId) else { return }
        show(cached)
        hasSnapshot = true
    }

    func saveSnapshot<T: Encodable>(_ value: T, key: String, api: APIClient) {
        DiskCache.save(value, key: key, userId: api.currentUserId)
    }

    func markLoaded() {
        hasSnapshot = true
        offline = false
    }

    /// الإلغاء والجلب القديم بيتجاهلوا؛ انقطاع ومعنا محتوى → `offline`؛ غير هيك → `fallback`.
    func failLoad(_ error: Error, generation: Int, fallback: () -> Void) {
        guard !error.isCancellation, isCurrentLoad(generation) else { return }
        if hasSnapshot && Self.isConnectionError(error) {
            offline = true
        } else {
            offline = false
            fallback()
        }
    }

    /// A delete with «تراجع»: off the screen now (`remove`), sent with `call` only when the
    /// undo offer ends; undone, or refused by the server, `restore` puts it back.
    func deleteWithUndo(_ text: String, remove: () -> Void, restore: @escaping () -> Void,
                        call: @escaping () async throws -> Void) {
        remove()
        UndoCenter.shared.offer(String(format: LanguageManager.shared.s("blocks.deletedToast"), text),
                                icon: "trash", undo: restore,
                                commit: { self.optimistic("blocks.errorSave", apply: {}, rollback: restore, call: call) })
    }

    /// Optimistic mutation: `apply` now, `call` in the background, `rollback` + notice on failure.
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
