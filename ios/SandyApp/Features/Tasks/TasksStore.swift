import SwiftUI

/// يملك مهام المستخدم والجلب والتعديلات، منفصل عن دورة حياة الشاشة. مفتاح الحل:
/// الجلب بيشتغل بمهمة **مملوكة للستور** (`loadTask`)، فلمّا إيماءة السحب/التنقّل
/// تنتهي وتلغي إطار الواجهة، الجلب بيكمّل ويحدّث `tasks` — والجديد يبيّن دايماً.
/// هاي معمارية "مصدر حقيقة واحد"، نفس نمط التطبيقات الكبيرة.
@MainActor
final class TasksStore: LoadableStore {
    @Published var tasks: [TaskItem] = [] {
        didSet { scheduleNotifications() }
    }
    /// رسالة ودّية بصوت ساندي (فاضية = ما في خطأ).

    private var loadTask: Task<Void, Never>?
    /// آخر فلتر مُحمّل — ما نجدول إشعارات إلا للنشطة (عرض المكتملة ما يمسحها).
    private var showingCompleted = false

    /// إشعار محلي لكل مهمة نشطة إلها موعد. الموعد بلا وقت (منتصف الليل) → التاسعة
    /// صباحاً بدل منتصفه. المكتملة والماضية تُتجاهل.
    private func scheduleNotifications() {
        guard !showingCompleted else { return }
        let isAR = AppLocale.isArabic   // لغة التطبيق، مش لغة الجهاز
        let title = isAR ? "مهمة" : "Task"
        let cal = Calendar.current
        let items = tasks.compactMap { t -> NotificationItem? in
            guard !t.done, var date = NotificationManager.parseISO(t.dueAt) else { return nil }
            let c = cal.dateComponents([.hour, .minute], from: date)
            if (c.hour ?? 0) == 0 && (c.minute ?? 0) == 0 {
                date = cal.date(bySettingHour: 9, minute: 0, second: 0, of: date) ?? date
            }
            return NotificationItem(id: t.id, title: title, body: t.text, date: date)
        }
        NotificationManager.shared.sync(prefix: "task.", items: items)

        // لقطة الويدجت: عدد المهام النشطة.
        WidgetData.setOpenTasks(tasks.filter { !$0.done })
        WidgetData.setActiveTasks(count: tasks.filter { !$0.done }.count)
    }

    /// يبدأ جلباً مملوكاً للستور وينتظره — يصلح للـ `.task` و`.refreshable` معاً.
    /// لو انلغى انتظار الواجهة، المهمة المملوكة بتكمّل وبتحدّث الحالة.
    func load(api: APIClient, completed: Bool) async {
        loadTask?.cancel()
        let gen = beginLoad()
        let cacheKey = completed ? "tasks.completed" : "tasks"
        // وضع بدون إنترنت: أول تحميل (أو تبديل الفلتر) بيعرض النسخة المحفوظة فورًا.
        if !hasSnapshot || completed != showingCompleted {
            if let cached = DiskCache.load(CachedList<CachedTask>.self, key: cacheKey,
                                           userId: api.currentUserId) {
                showingCompleted = completed
                tasks = cached.items.map(\.model)
                demo = cached.demo
                hasSnapshot = true
            } else if completed != showingCompleted {
                hasSnapshot = false
            }
        }
        let task = Task { @MainActor in
            defer { endLoad(gen) }
            do {
                let r = try await api.getTasks(completed: completed)
                guard isCurrentLoad(gen) else { return }
                showingCompleted = completed
                tasks = r.items
                demo = r.demo
                markLoaded()
                DiskCache.save(CachedList(items: r.items.map { CachedTask($0) }, demo: r.demo),
                               key: cacheKey, userId: api.currentUserId)
                if !completed && !r.demo { SpotlightIndexer.indexTasks(r.items) }
            } catch {
                failLoad(error, generation: gen) { notify("tasks.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة مهمة ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, text: String, due: String, note: String?, priority: String) async -> Bool {
        do {
            try await api.addTask(text: text, due: due, note: note, priority: priority)
            clearNotice()
            await load(api: api, completed: false)
            return true
        } catch {
            notify("tasks.errorAdd")
            return false
        }
    }

    /// تبديل الإنجاز بتحديث متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func toggle(api: APIClient, task: TaskItem) {
        guard let idx = tasks.firstIndex(where: { $0.id == task.id }) else { return }
        let target = !task.done
        optimistic(
            "tasks.errorToggle",
            apply: { self.tasks[idx].done = target },
            rollback: {
                if let i = self.tasks.firstIndex(where: { $0.id == task.id }) { self.tasks[i].done = !target }
            },
            call: { try await api.setTaskDone(id: task.id, done: target) }
        )
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, task: TaskItem) {
        guard let idx = tasks.firstIndex(where: { $0.id == task.id }) else { return }
        let removed = tasks[idx]
        optimistic(
            "tasks.errorDelete",
            apply: { self.tasks.remove(at: idx) },
            rollback: { self.tasks.insert(removed, at: min(idx, self.tasks.count)) },
            call: { try await api.deleteTask(id: task.id) }
        )
    }

    /// تعديل شامل (نص/موعد/ملاحظة/أولوية) ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة.
    func update(api: APIClient, id: String, text: String, due: String,
                note: String?, priority: String, completed: Bool) async -> Bool {
        do {
            try await api.updateTask(id: id, text: text, note: note ?? "",
                                     priority: priority, due: due)
            clearNotice()
            await load(api: api, completed: completed)
            return true
        } catch {
            notify("tasks.errorEdit")
            return false
        }
    }

    /// تغيير الأولوية سريعًا (من القائمة السياقية) بتحديث متفائل.
    func setPriority(api: APIClient, task: TaskItem, priority: String) {
        guard let idx = tasks.firstIndex(where: { $0.id == task.id }) else { return }
        let old = tasks[idx].priority
        optimistic(
            "tasks.errorEdit",
            apply: { self.tasks[idx].priority = priority },
            rollback: {
                if let i = self.tasks.firstIndex(where: { $0.id == task.id }) { self.tasks[i].priority = old }
            },
            call: { try await api.updateTask(id: task.id, priority: priority) }
        )
    }
}
