import SwiftUI

@MainActor
final class HomeStore: LoadableStore {
    @Published var snapshot = HomeSnapshot()
    @Published var loadFailed = false
    @Published var didAppear = false
    @Published var revealKey = 0
    /// ترتيب عناصر الرئيسية الذي اختاره المستخدم (محفوظ محليًا).
    @Published var order: [HomeBlock] = HomeBlock.allCases

    private var loadTask: Task<Void, Never>?
    private let orderKey = "sandy_home_order"

    override init() {
        super.init()
        loadOrder()
    }

    /// يقرأ الترتيب المحفوظ ويُلحق أي عنصر جديد ما كان موجود (هجرة آمنة).
    func loadOrder() {
        let saved = UserDefaults.standard.stringArray(forKey: orderKey) ?? []
        var result = saved.compactMap { HomeBlock(rawValue: $0) }
        for b in HomeBlock.allCases where !result.contains(b) { result.append(b) }
        order = result
    }

    /// إعادة ترتيب عنصر (من ورقة الترتيب) ثم حفظ فوري.
    func move(from offsets: IndexSet, to destination: Int) {
        order.move(fromOffsets: offsets, toOffset: destination)
        UserDefaults.standard.set(order.map(\.rawValue), forKey: orderKey)
    }

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
