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
    /// التطبيق (AppLocale، بلا main actor)، ونصّه نص التذكير نفسه. الماضي يُتجاهل تلقائيًا.
    private func scheduleNotifications() {
        let isAR = AppLocale.isArabic   // لغة التطبيق، مش لغة الجهاز
        let title = isAR ? "تذكير" : "Reminder"
        let items = reminders.compactMap { r -> NotificationItem? in
            guard let date = NotificationManager.parseISO(r.remindAt) else { return nil }
            // الفئة بتحطّ أزرار «بعدين / تمّ / احذف» على الإشعار، والحمولة بتخلّي
            // الزرّ ينفّذ حتى لو التطبيق مو شغّال.
            return NotificationItem(
                id: r.id, title: title, body: r.text, date: date,
                repeats: NotificationRepeat(rrule: r.recurrence),
                category: NotificationManager.reminderCategory,
                userInfo: [NotificationManager.reminderIdKey: r.id,
                           NotificationManager.reminderRecurrenceKey: r.recurrence])
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
        let gen = beginLoad()
        let cacheKey = "reminders"
        if !hasSnapshot, let cached = DiskCache.load(CachedList<CachedReminder>.self, key: cacheKey,
                                                     userId: api.currentUserId) {
            reminders = cached.items.map(\.model)
            demo = cached.demo
            hasSnapshot = true
        }
        let task = Task { @MainActor in
            defer { endLoad(gen) }
            do {
                let r = try await api.getReminders()
                guard isCurrentLoad(gen) else { return }
                reminders = r.items
                demo = r.demo
                markLoaded()
                DiskCache.save(CachedList(items: r.items.map { CachedReminder($0) }, demo: r.demo),
                               key: cacheKey, userId: api.currentUserId)
                if !r.demo { SpotlightIndexer.indexReminders(r.items) }
            } catch {
                failLoad(error, generation: gen) { notify("reminders.loadFailed") }
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

    /// ترتيب بالتاريخ المُحلَّل، مو بالنص: الخادم بيرجّع بتوقيت المستخدم وتخميننا
    /// المحلي بـUTC، فالمقارنة النصّية بتكذب.
    private nonisolated static func soonestFirst(_ lhs: ReminderItem, _ rhs: ReminderItem) -> Bool {
        let a: Date = NotificationManager.parseISOOrDay(lhs.remindAt) ?? .distantFuture
        let b: Date = NotificationManager.parseISOOrDay(rhs.remindAt) ?? .distantFuture
        return a < b
    }

    /// حذف تفاؤلي ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, reminder: ReminderItem) {
        guard let idx = reminders.firstIndex(where: { $0.id == reminder.id }) else { return }
        let removed = reminders[idx]
        optimistic(
            "reminders.actionFailed",
            apply: {
                self.reminders.remove(at: idx)
                Haptics.play(.success)
            },
            rollback: {
                self.reminders.insert(removed, at: min(idx, self.reminders.count))
                Haptics.play(.failure)
            },
            call: { try await api.deleteReminder(id: reminder.id) }
        )
    }

    /// «ذكّرني بعدين»: نحرّك الوقت محليًا على طول، والخادم بيقول الوقت الحقيقي.
    /// التكرار ما بينلمس — التذكير اليومي بيرجع لساعته بعد هالمرّة.
    func snooze(api: APIClient, reminder: ReminderItem, minutes: Int) {
        guard let idx = reminders.firstIndex(where: { $0.id == reminder.id }) else { return }
        let previous = reminders[idx].remindAt
        let guessed = ISO8601DateFormatter().string(
            from: Date().addingTimeInterval(TimeInterval(minutes) * 60))
        optimistic(
            "reminders.actionFailed",
            apply: {
                self.reminders[idx].remindAt = guessed
                Haptics.play(.selection)
            },
            rollback: {
                if let i = self.reminders.firstIndex(where: { $0.id == reminder.id }) {
                    self.reminders[i].remindAt = previous
                }
                Haptics.play(.failure)
            },
            call: {
                let out = try await api.snoozeReminder(id: reminder.id, minutes: minutes)
                // الخادم بيرجّع الوقت المضبوط — نصلّح تخميننا بلا إعادة جلب.
                let exact = out.remindAt
                guard !exact.isEmpty else { return }
                await MainActor.run {
                    if let i = self.reminders.firstIndex(where: { $0.id == reminder.id }) {
                        self.reminders[i].remindAt = exact
                    }
                }
            }
        )
    }

    /// «تمّ»: التذكير اللي مرّة وحدة بيختفي، والمتكرّر بيضلّ بس بموعده الجاي.
    func markDone(api: APIClient, reminder: ReminderItem) {
        guard let idx = reminders.firstIndex(where: { $0.id == reminder.id }) else { return }
        let removed = reminders[idx]
        optimistic(
            "reminders.actionFailed",
            apply: {
                self.reminders.remove(at: idx)
                Haptics.play(.success)
            },
            rollback: {
                self.reminders.insert(removed, at: min(idx, self.reminders.count))
                Haptics.play(.failure)
            },
            call: {
                let out = try await api.completeReminder(id: reminder.id)
                // متكرّر: بيرجع للقائمة بموعده الجاي بدل ما يختفي.
                let nextAt = out.remindAt
                guard !nextAt.isEmpty else { return }
                await MainActor.run {
                    var next = removed
                    next.remindAt = nextAt
                    self.reminders.insert(next, at: min(idx, self.reminders.count))
                    self.reminders.sort(by: Self.soonestFirst)
                }
            }
        )
    }
}
