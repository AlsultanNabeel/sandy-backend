import Foundation
import OSLog
import UserNotifications
#if canImport(UIKit)
import UIKit
#endif

// ─────────────────────────────────────────────────────────────────────────
//  NotificationManager — مدير الإشعارات المحلية المركزي.
//
//  يطلب الإذن مرّة، ويجدول إشعارًا لكل عنصر إله وقت مستقبلي (تذكير/رسالة
//  مستقبلية…). هوية الإشعار = بادئة النوع + هوية العنصر، فإعادة الجدولة تستبدل
//  القديم بلا تكرار، والمواعيد الماضية تُتجاهل.
//
//  الإشعار المحلي بيوصل والتطبيق مسكّر/مقفول (النظام يطلّعه) طالما تجدول مسبقًا
//  والإذن مُعطى. هاد أساس مستقل تمامًا عن الدفع البعيد (APNs) — لاحقًا بنركّب
//  الدفع فوقه (تسجيل توكن + إرسال من الباك‑إند) بلا ما نلمس هالكود.
//
//  iOS 16-safe — UserNotifications فقط. الصنف thread-safe (UNUserNotificationCenter
//  آمن للنداء من أي خيط) فما نعزله بـ main actor.
// ─────────────────────────────────────────────────────────────────────────

/// عنصر قابل للجدولة — يبنيه الستور من بياناته.
struct NotificationItem {
    let id: String
    let title: String
    let body: String
    let date: Date
    /// How it repeats, from the reminder's RRULE. `.none` rings once.
    var repeats: NotificationRepeat = .none
    /// The action category the notification carries (buttons on the banner /
    /// lock screen). nil = a plain notification with nothing to press.
    var category: String? = nil
    /// Whatever the buttons need to act without the app having been running —
    /// for a reminder that is its id and its recurrence rule.
    var userInfo: [String: String] = [:]
}

/// The repeat patterns a local notification can express by itself. A reminder
/// that repeats in a way this cannot express rings at its next occurrence, and
/// the server moves it forward the next time the list is loaded.
enum NotificationRepeat {
    case none, daily, weekly, monthly

    init(rrule: String) {
        // "RRULE:FREQ=WEEKLY;BYDAY=MO" → ["FREQ": "WEEKLY", "BYDAY": "MO"]
        var parts: [String: String] = [:]
        let body = rrule.uppercased().replacingOccurrences(of: "RRULE:", with: "")
        for pair in body.split(separator: ";") {
            let kv = pair.split(separator: "=", maxSplits: 1).map(String.init)
            if kv.count == 2 { parts[kv[0]] = kv[1] }
        }
        // Only what one calendar trigger can express: every single day, one day
        // a week, or one day a month. "Every 2 days" or "Mon and Wed" cannot.
        if let n = parts["INTERVAL"], n != "1" { self = .none; return }
        let days = parts["BYDAY"].map { $0.split(separator: ",").count } ?? 0
        switch parts["FREQ"] {
        case "DAILY" where days == 0:   self = .daily
        case "WEEKLY" where days <= 1:  self = .weekly
        case "MONTHLY" where days == 0: self = .monthly
        default:                        self = .none
        }
    }
}

/// وجهة النقر على الإشعار — الشاشة اللي نفتحها حسب نوع الإشعار.
enum NotifRoute: String, Identifiable {
    case reminders, tasks, future, dailyNudge, insights
    var id: String { rawValue }
}

/// الأزرار اللي بتطلع على إشعار التذكير. القيمة الخام هي هوية الإجراء عند النظام.
enum ReminderNotificationAction: String {
    case snooze = "SANDY_REMINDER_SNOOZE"
    case done   = "SANDY_REMINDER_DONE"
    case delete = "SANDY_REMINDER_DELETE"
}

final class NotificationManager: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationManager()
    private let center = UNUserNotificationCenter.current()

    /// تُضبط عند النقر على إشعار → الواجهة تفتح شاشتها. تُصفّر بعد الفتح.
    @Published var pendingRoute: NotifRoute?

    /// يزيد كل ما زرّ بإشعار تذكير غيّر شي بالخادم (بعدين/تمّ/احذف)، فشاشة
    /// التذكيرات — لو كانت مفتوحة — تعيد الجلب بدل ما تعرض وقتًا قديمًا.
    @Published var remindersChanged = 0

    /// يُستدعى بتوكن جهاز APNs (نص hex) عند نجاح التسجيل للدفع البعيد — يضبطه
    /// AppState حتى يرفعه للباك-إند (`/api/push/register`). نخزّن آخر توكن حتى لو
    /// وصل قبل ما يُضبط المستمع، فنقدر نرفعه أول ما يجهز.
    var onDeviceToken: ((String) -> Void)?
    private(set) var lastDeviceToken: String?

    private override init() {
        super.init()
        // مندوب المركز — حتى يطلع الإشعار كبانر والتطبيق مفتوح، ونمسك النقر للتوجيه.
        center.delegate = self
        // أزرار التذكير لازم تكون مسجّلة قبل ما يوصل أي إشعار — والنظام بيشغّل
        // التطبيق بالخلفية عشان يسلّمنا ضغطة زر، فهاد أوّل شي بينفّذ وقتها.
        registerReminderCategory()
        // كل ما يرجع التطبيق للواجهة نعيد جدولة الإشعارات الاستباقية — فإشعار
        // «صارلك يومين» بيتأجّل مع كل فتحة، وما بيطلع إلا لو المستخدم غاب فعلًا.
        #if canImport(UIKit)
        NotificationCenter.default.addObserver(
            forName: UIApplication.didBecomeActiveNotification,
            object: nil, queue: .main
        ) { _ in
            NotificationManager.shared.scheduleProactiveNudges()
        }
        #endif
    }

    /// نطلب الإذن (تنبيه/صوت/شارة)، وعند الموافقة نسجّل الجهاز للدفع البعيد (APNs).
    /// آمن للنداء المتكرّر — النظام يعرض الطلب مرّة، والتسجيل idempotent.
    func requestAuthorization() {
        center.requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
            guard granted else { return }
            #if canImport(UIKit)
            DispatchQueue.main.async {
                UIApplication.shared.registerForRemoteNotifications()
            }
            #endif
        }
    }

    /// يستقبله AppDelegate عند نجاح التسجيل: نحوّل بايتات التوكن لـ hex ونمرّرها
    /// للمستمع (لرفعها للباك-إند). لو ما في مستمع بعد، نحتفظ فيه لآخر.
    func handleDeviceToken(_ deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        lastDeviceToken = hex
        onDeviceToken?(hex)
    }

    /// يربط المستمع ويرفع أي توكن وصل مسبقًا (لو التسجيل سبق ضبط المستمع).
    func bindDeviceToken(_ handler: @escaping (String) -> Void) {
        onDeviceToken = handler
        if let t = lastDeviceToken { handler(t) }
    }

    /// التطبيق مفتوح: نعرض الإشعار كبانر + صوت + ضمن قائمة الإشعارات.
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler:
                                    @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .list])
    }

    /// النقر على الإشعار: نقرأ نوعه من بادئة الهوية ونوجّه الواجهة لشاشته.
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        // زرّ على تذكير: ننفّذه بدل ما نفتح التطبيق وبس. هالمسار بيشتغل كمان
        // والتطبيق مو شغّال أصلًا — النظام بيقلّعه بالخلفية ويسلّمنا الرد، و
        // الـAPIClient تحت بيقرا توكنه من الـKeychain متل الويدجت والاختصارات.
        if let action = ReminderNotificationAction(rawValue: response.actionIdentifier),
           let reminderId = response.notification.request.content
               .userInfo[Self.reminderIdKey] as? String,
           !reminderId.isEmpty {
            perform(action, reminderId: reminderId,
                    notification: response.notification.request,
                    completion: completionHandler)
            return
        }

        let id = response.notification.request.identifier
        // الدفع البعيد للتنبيه اليومي يحمل "kind" بالحمولة (agenda/question) — نوجّهه
        // للرئيسية حيث تظهر بطاقة التنبيه. المحلّي يُعرف ببادئة هويته.
        let userInfo = response.notification.request.content.userInfo
        let route: NotifRoute? = (userInfo["kind"] != nil)
            ? .dailyNudge
            : Self.route(forIdentifier: id)
        if let route {
            DispatchQueue.main.async { self.pendingRoute = route }
        }
        completionHandler()
    }

    /// وجهة إشعار محلي من بادئة هويته (nil = يفتح التطبيق بس).
    static func route(forIdentifier id: String) -> NotifRoute? {
        if id.hasPrefix(weeklyID) { return .insights }
        if id.hasPrefix(headsUpPrefix + "task.") { return .tasks }
        if id.hasPrefix(headsUpPrefix) { return .reminders }
        if id.hasPrefix("reminder.") { return .reminders }
        if id.hasPrefix("task.") { return .tasks }
        if id.hasPrefix("future.") { return .future }
        return nil
    }

    /// نزامن إشعارات نوع كامل بنفس البادئة: نلغي كل المعلّق بهالبادئة ثم نجدول
    /// العناصر المستقبلية. البادئة تفصل الأنواع فما يتعارضوا (تذكير/رسالة/…).
    func sync(prefix: String, items: [NotificationItem]) {
        center.getPendingNotificationRequests { [weak self] reqs in
            guard let self else { return }
            let stale = reqs.map(\.identifier).filter { $0.hasPrefix(prefix) }
            self.center.removePendingNotificationRequests(withIdentifiers: stale)
            for it in items {
                self.schedule(id: prefix + it.id, title: it.title, body: it.body,
                              at: it.date, repeats: it.repeats,
                              category: it.category, userInfo: it.userInfo)
            }
        }
        // نتذكّر عناصر كل نوع حتى تنبيهات «بعد ساعة» تنبني منها وتتجنّب التكرار.
        knownLock.lock()
        knownItems[prefix] = items
        knownLock.unlock()
        scheduleProactiveNudges()
    }

    /// Tears down everything this device holds for the account signing out.
    ///
    /// Every notification here was scheduled from one account's data: their
    /// reminders, their tasks, the heads-up an hour before something only they
    /// have. None of it is re-checked at fire time — a local notification just
    /// rings — so without this the next person to sign in on this phone gets
    /// the previous account's reminders, by name, for as long as they were
    /// scheduled ahead. `knownItems` goes with them: it is what
    /// `scheduleProactiveNudges` rebuilds from, so leaving it would put the old
    /// account's items straight back on the next sync.
    ///
    /// `removeAllPending…` rather than a prefix sweep: the point is that
    /// nothing scheduled before this moment survives it, and a prefix list is
    /// one forgotten prefix away from being wrong.
    func clearForSignOut() {
        center.removeAllPendingNotificationRequests()
        center.removeAllDeliveredNotifications()
        knownLock.lock()
        knownItems.removeAll()
        knownLock.unlock()
        onDeviceToken = nil
    }

    // MARK: - Reminder actions (the buttons on a reminder's notification)

    /// The category every reminder notification carries; its buttons are built
    /// in `registerReminderCategory()`.
    static let reminderCategory = "SANDY_REMINDER"
    /// userInfo keys the buttons read back — the two things acting needs.
    static let reminderIdKey = "reminder_id"
    static let reminderRecurrenceKey = "reminder_recurrence"
    /// What «remind me later» means from the lock screen, where there is no room
    /// to ask. Matches the backend's own default.
    static let snoozeMinutes = 10

    /// Registers the three buttons. Titles are baked in when the category is
    /// registered, not when the notification fires, so this runs again whenever
    /// the app language changes (`LanguageManager.setLang`).
    func registerReminderCategory() {
        let lang = AppLocale.lang
        let snooze = UNNotificationAction(
            identifier: ReminderNotificationAction.snooze.rawValue,
            title: translate(lang, "reminders.snooze"),
            options: [])
        let done = UNNotificationAction(
            identifier: ReminderNotificationAction.done.rawValue,
            title: translate(lang, "reminders.done"),
            options: [])
        let remove = UNNotificationAction(
            identifier: ReminderNotificationAction.delete.rawValue,
            title: translate(lang, "reminders.delete"),
            options: [.destructive])
        center.setNotificationCategories([
            UNNotificationCategory(identifier: Self.reminderCategory,
                                   actions: [snooze, done, remove],
                                   intentIdentifiers: [],
                                   options: [])
        ])
    }

    /// Runs one button: the backend first, then the local notification is
    /// re-armed or left cancelled to match, then an open reminders screen is
    /// told to refetch.
    ///
    /// The server is the source of truth for this list, so a failure here is
    /// recoverable rather than silent: the next time the reminders screen loads,
    /// `sync(prefix:items:)` rebuilds every reminder notification from it.
    private func perform(_ action: ReminderNotificationAction,
                         reminderId: String,
                         notification: UNNotificationRequest,
                         completion: @escaping () -> Void) {
        // The user answered this one — take it down before anything else.
        let notifId = notification.identifier
        center.removeDeliveredNotifications(withIdentifiers: [notifId])
        center.removePendingNotificationRequests(withIdentifiers: [notifId])

        let content = notification.content
        let recurrence = content.userInfo[Self.reminderRecurrenceKey] as? String ?? ""
        let info = [Self.reminderIdKey: reminderId,
                    Self.reminderRecurrenceKey: recurrence]

        // المدير كائن واجهة (ObservableObject) — بننفّذ ع الخيط الرئيسي بدل ما
        // نمرّره لإغلاق متوازٍ.
        Task { @MainActor [weak self] in
            guard let self else { completion(); return }
            let api = APIClient(baseURL: Backend.currentURL)   // التوكن من الـKeychain
            do {
                switch action {
                case .snooze:
                    let out = try await api.snoozeReminder(id: reminderId,
                                                           minutes: Self.snoozeMinutes)
                    // One shot on purpose: a repeating trigger built from the
                    // snoozed time would ring ten minutes late every day after.
                    // The series itself is intact on the server and comes back
                    // with the next load.
                    if let at = Self.parseISO(out.remindAt) {
                        self.schedule(id: notifId, title: content.title, body: content.body,
                                      at: at, category: Self.reminderCategory, userInfo: info)
                    }
                case .done:
                    let out = try await api.completeReminder(id: reminderId)
                    // A recurring reminder answers with its next occurrence (its
                    // own hour, not the snoozed one); a one-off answers with
                    // nothing and stays cancelled.
                    if let at = Self.parseISO(out.remindAt) {
                        self.schedule(id: notifId, title: content.title, body: content.body,
                                      at: at, repeats: NotificationRepeat(rrule: recurrence),
                                      category: Self.reminderCategory, userInfo: info)
                    }
                case .delete:
                    try await api.deleteReminder(id: reminderId)
                }
                self.remindersChanged &+= 1
            } catch {
                Logger(subsystem: Bundle.main.bundleIdentifier ?? "SandyApp",
                       category: "reminders")
                    .error("reminder action failed: \(error.localizedDescription, privacy: .public)")
            }
            completion()
        }
    }

    // MARK: - Proactive nudges (local — APNs isn't configured)

    /// All proactive identifiers share this root, so they never collide with the
    /// per-item prefixes above, and a reschedule replaces instead of stacking.
    static let proactivePrefix = "proactive."
    static let awayID = "proactive.away"
    static let weeklyID = "proactive.weekly"
    static let headsUpPrefix = "proactive.headsUp."

    /// The last items `sync` saw per prefix ("task." / "reminder." / "future.").
    private var knownItems: [String: [NotificationItem]] = [:]
    private let knownLock = NSLock()

    /// Reschedules Sandy's proactive local notifications. Safe to call often
    /// (every app activation and after every task/reminder load):
    ///  • away — one ping 48h from now; each open pushes it forward again, so it
    ///    only fires if the user really disappears for two days;
    ///  • heads-up — 60 minutes before each task/reminder that has a time later
    ///    today, unless something already rings at that exact time;
    ///  • weekly — Sunday 19:00 «your week is ready», opening the Insights screen.
    /// Does nothing (and clears what it scheduled) when notifications are denied.
    func scheduleProactiveNudges() {
        knownLock.lock()
        let known = knownItems
        knownLock.unlock()
        center.getNotificationSettings { [weak self] settings in
            guard let self else { return }
            let allowed: [UNAuthorizationStatus] = [.authorized, .provisional, .ephemeral]
            guard allowed.contains(settings.authorizationStatus) else {
                self.center.getPendingNotificationRequests { reqs in
                    let ours = reqs.map(\.identifier).filter { $0.hasPrefix(Self.proactivePrefix) }
                    self.center.removePendingNotificationRequests(withIdentifiers: ours)
                }
                return
            }
            let lang = AppLocale.lang

            // (a) صارلك يومين ما حكيتني — same id, so this replaces the previous one.
            self.addProactive(
                id: Self.awayID,
                title: translate(lang, "insights.notif.away.title"),
                body: translate(lang, "insights.notif.away.body"),
                trigger: UNTimeIntervalNotificationTrigger(timeInterval: 48 * 3600, repeats: false))

            // (c) Sunday evening — weekday 1 is Sunday in the Gregorian calendar.
            var sunday = DateComponents()
            sunday.weekday = 1
            sunday.hour = 19
            sunday.minute = 0
            self.addProactive(
                id: Self.weeklyID,
                title: translate(lang, "insights.notif.weekly.title"),
                body: translate(lang, "insights.notif.weekly.body"),
                trigger: UNCalendarNotificationTrigger(dateMatching: sunday, repeats: true))

            // (b) heads-up an hour before today's timed tasks/reminders.
            let heads = Self.headsUps(known: known, now: Date())
            let wanted = Set(heads.map(\.id))
            self.center.getPendingNotificationRequests { reqs in
                let stale = reqs.map(\.identifier).filter {
                    $0.hasPrefix(Self.headsUpPrefix) && !wanted.contains($0)
                }
                self.center.removePendingNotificationRequests(withIdentifiers: stale)
                for h in heads {
                    let comps = Calendar.current.dateComponents(
                        [.year, .month, .day, .hour, .minute], from: h.date)
                    self.addProactive(
                        id: h.id,
                        title: translate(lang, "insights.notif.headsUp.title"),
                        body: String(format: translate(lang, "insights.notif.headsUp.body"), h.text),
                        trigger: UNCalendarNotificationTrigger(dateMatching: comps, repeats: false))
                }
            }
        }
    }

    /// The heads-ups to schedule: items later today whose "one hour before" is
    /// still ahead and doesn't coincide (±1 min) with any notification we
    /// already schedule. A task with no time was moved to 09:00 by its store,
    /// so 09:00 sharp on a task is treated as "no time" and skipped.
    private static func headsUps(known: [String: [NotificationItem]],
                                 now: Date) -> [HeadsUp] {
        let cal = Calendar.current
        let allDates = known.values.flatMap { $0.map(\.date) }
        var out: [HeadsUp] = []
        for prefix in ["task.", "reminder."] {
            for it in known[prefix] ?? [] {
                guard cal.isDateInToday(it.date) else { continue }
                let at = it.date.addingTimeInterval(-3600)
                guard at > now else { continue }
                if prefix == "task." {
                    let c = cal.dateComponents([.hour, .minute, .second], from: it.date)
                    if c.hour == 9 && c.minute == 0 && (c.second ?? 0) == 0 { continue }
                }
                if allDates.contains(where: { abs($0.timeIntervalSince(at)) < 60 }) { continue }
                out.append(HeadsUp(id: headsUpPrefix + prefix + it.id, text: it.body, date: at))
            }
        }
        return out
    }

    private struct HeadsUp {
        let id: String
        let text: String
        let date: Date
    }

    private func addProactive(id: String, title: String, body: String,
                              trigger: UNNotificationTrigger) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        center.add(UNNotificationRequest(identifier: id, content: content, trigger: trigger))
    }

    /// إشعار واحد بهوية ثابتة (يستبدل أي قديم بنفس الهوية). الماضي يُتجاهل.
    private func schedule(id: String, title: String, body: String, at date: Date,
                          repeats: NotificationRepeat = .none,
                          category: String? = nil,
                          userInfo: [String: String] = [:]) {
        guard date > Date() || repeats != .none else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        // الفئة بتجيب معها الأزرار (بعدين/تمّ/احذف)، والحمولة بتخلّي الزرّ يقدر
        // ينفّذ بلا ما يفتح التطبيق ولا يجيب القائمة.
        if let category { content.categoryIdentifier = category }
        if !userInfo.isEmpty {
            var payload: [AnyHashable: Any] = [:]
            for (key, value) in userInfo { payload[key] = value }
            content.userInfo = payload
        }
        // A repeating reminder used to be scheduled once and never again, so
        // "every day at 8" rang on the first day only. The matching components
        // decide the repeat: time of day, plus weekday or day of month.
        let fields: Set<Calendar.Component>
        switch repeats {
        case .none:    fields = [.year, .month, .day, .hour, .minute]
        case .daily:   fields = [.hour, .minute]
        case .weekly:  fields = [.weekday, .hour, .minute]
        case .monthly: fields = [.day, .hour, .minute]
        }
        let comps = Calendar.current.dateComponents(fields, from: date)
        let trigger = UNCalendarNotificationTrigger(dateMatching: comps, repeats: repeats != .none)
        center.add(UNNotificationRequest(identifier: id, content: content, trigger: trigger))
    }

    /// مُحلِّل ISO متسامح — الباك‑إند قد يرسل بمنطقة زمنية، بكسور ثانية، أو بدون.
    /// المحلّلات مبنية مرّة وحدة: بناء الـformatter غالي، وهالدالة بتنادى لكل
    /// صف بالقوائم ولكل جسم عرض. التحليل من عدّة خيوط آمن عليها من iOS 7.
    private static let isoFrac: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let isoPlain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    /// بدون منطقة زمنية (مثل "2026-06-05T16:00:00") — نفسّره بالتوقيت المحلي.
    private static let isoNoTZ: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f
    }()

    static func parseISO(_ s: String) -> Date? {
        if s.isEmpty { return nil }
        return isoFrac.date(from: s)
            ?? isoPlain.date(from: s)
            ?? isoNoTZ.date(from: s)
    }

    /// تاريخ بلا وقت (مثل "2026-06-05") — نفسّره بالتوقيت المحلي.
    private static let isoDayOnly: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone.current
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    /// مثل `parseISO` بس بيقبل كمان تاريخ بلا وقت — للرئيسية والتذكيرات والهدايا.
    static func parseISOOrDay(_ s: String) -> Date? {
        if s.isEmpty { return nil }
        return parseISO(s) ?? isoDayOnly.date(from: s)
    }
}
