import SwiftUI

@MainActor
final class HomeStore: LoadableStore {
    @Published var snapshot = HomeSnapshot()
    @Published var loadFailed = false
    @Published var didAppear = false
    @Published var revealKey = 0
    private var loadTask: Task<Void, Never>?
    /// تحميل أوّل فقط (يتحكّم بدخول البطاقات المتدرّج).
    func loadIfNeeded(api: APIClient) async {
        guard !didAppear else { return }
        await load(api: api)
    }

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            let snap = await api.getHomeSnapshot()
            let fullFail = snap.hadError
                && snap.openTasks == 0
                && snap.upcomingReminders.isEmpty
                && snap.weekExpenseTotal == 0
            // ما نمسح لوحة جيدة على خطأ/إلغاء عابر: نحدّث فقط لو نجح أو لسا ما عندنا بيانات.
            if !snap.hadError || !didAppear {
                snapshot = snap
                loadFailed = fullFail
            }
            didAppear = true
            revealKey += 1   // يعيد تشغيل دخول البطاقات المتدرّج.
        }
        loadTask = task
        await task.value
    }
}
