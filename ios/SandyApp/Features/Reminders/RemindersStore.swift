import SwiftUI

/// يملك تذكيرات المستخدم والجلب والتعديلات، مستقل عن دورة حياة الشاشة. الجلب
/// بمهمة مملوكة للستور، فإلغاء إيماءة السحب ما يلغيه — والجديد يبيّن دايماً.
@MainActor
final class RemindersStore: LoadableStore {
    /// أي تغيير على القائمة (جلب/إضافة/تعديل/حذف) يعيد جدولة الإشعارات المحلية.
    @Published var reminders: [ReminderItem] = [] {
        didSet { scheduleNotifications() }
    }

    private var loadTask: Task<Void, Never>?

    /// نجدول إشعارًا محليًا لكل تذكير إله وقت مستقبلي. عنوان الإشعار حسب لغة
    /// الجهاز (نتجنّب main actor)، ونصّه نص التذكير نفسه. الماضي يُتجاهل تلقائيًا.
    private func scheduleNotifications() {
        let isAR = Locale.current.language.languageCode?.identifier == "ar"
        let title = isAR ? "تذكير" : "Reminder"
        let items = reminders.compactMap { r -> NotificationItem? in
            guard let date = NotificationManager.parseISO(r.remindAt) else { return nil }
            return NotificationItem(id: r.id, title: title, body: r.text, date: date)
        }
        NotificationManager.shared.sync(prefix: "reminder.", items: items)

        // لقطة الويدجت: أقرب تذكير قادم.
        let now = Date()
        let next = reminders
            .compactMap { r -> (String, Date)? in
                guard let d = NotificationManager.parseISO(r.remindAt), d > now else { return nil }
                return (r.text, d)
            }
            .min(by: { $0.1 < $1.1 })
        WidgetData.setNextReminder(text: next?.0, date: next?.1)
    }

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                let r = try await api.getReminders()
                reminders = r.items
                demo = r.demo
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("reminders.loadFailed") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة تذكير ثم إعادة جلب — يرمي عند الفشل ليتعامل الشيت معه.
    func add(api: APIClient, text: String, remindAt: String, note: String?) async throws {
        try await api.addReminder(text: text, remindAt: remindAt, note: note)
        await load(api: api)
    }

    /// تعديل تذكير ثم إعادة جلب — يرمي عند الفشل ليتعامل الشيت معه. الملاحظة
    /// تُرسل دايمًا (حتى الفاضية = مسح)، فنمرّر "" مو nil.
    func update(api: APIClient, id: String, text: String, remindAt: String, note: String?) async throws {
        try await api.updateReminder(id: id, text: text, remindAt: remindAt, note: note ?? "")
        await load(api: api)
    }

    /// حذف تفاؤلي ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, reminder: ReminderItem) {
        reminders.removeAll { $0.id == reminder.id }
        Task { @MainActor in
            do {
                try await api.deleteReminder(id: reminder.id)
            } catch {
                notice = LanguageManager.shared.s("reminders.loadFailed")
                await load(api: api)
            }
        }
    }
}
