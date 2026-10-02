import Foundation
import OSLog
import UserNotifications
#if canImport(UIKit)
import UIKit
#endif

// هوية الإشعار = بادئة النوع + هوية العنصر، فإعادة الجدولة تستبدل القديم بلا تكرار.
// UNUserNotificationCenter آمن من أي خيط، فما نعزل الصنف بـ main actor.

struct NotificationItem {
    let id: String
    let title: String
    let body: String
    let date: Date
    /// From the reminder's RRULE. `.none` rings once.
    var repeats: NotificationRepeat = .none
    /// Action category (banner buttons); nil = plain notification.
    var category: String? = nil
    /// What the buttons need to act without the app running (reminder id + rule).
    var userInfo: [String: String] = [:]
}

/// Repeats one calendar trigger can express; anything else rings once and the
/// server moves it forward on the next load.
enum NotificationRepeat {
    case none, daily, weekly, monthly

    init(rrule: String) {
        var parts: [String: String] = [:]
        let body = rrule.uppercased().replacingOccurrences(of: "RRULE:", with: "")
        for pair in body.split(separator: ";") {
            let kv = pair.split(separator: "=", maxSplits: 1).map(String.init)
            if kv.count == 2 { parts[kv[0]] = kv[1] }
        }
        // Daily, one weekday, or one day a month. "Every 2 days" or "Mon and Wed" cannot.
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

enum NotifRoute: String, Identifiable {
    case reminders, tasks, future, dailyNudge, insights
    var id: String { rawValue }
}

/// القيمة الخام هي هوية الإجراء عند النظام.
enum ReminderNotificationAction: String {
    case snooze = "SANDY_REMINDER_SNOOZE"
    case done   = "SANDY_REMINDER_DONE"
    case delete = "SANDY_REMINDER_DELETE"
}

final class NotificationManager: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationManager()
    private let center = UNUserNotificationCenter.current()

    /// النقر على إشعار → الواجهة تفتح شاشتها وتصفّره.
    @Published var pendingRoute: NotifRoute?

    /// يزيد كل ما زرّ بإشعار تذكير غيّر شي بالخادم، فشاشة التذكيرات تعيد الجلب.
    @Published var remindersChanged = 0

    /// آخر توكن APNs (hex) محفوظ حتى لو وصل قبل ما يُضبط المستمع.
    var onDeviceToken: ((String) -> Void)?
    private(set) var lastDeviceToken: String?

    private override init() {
        super.init()
        // حتى يطلع الإشعار كبانر والتطبيق مفتوح، ونمسك النقر.
        center.delegate = self
        // أزرار التذكير لازم تتسجّل قبل أي إشعار: النظام ممكن يشغّل التطبيق بالخلفية لضغطة زر.
        registerReminderCategory()
        // مع كل رجوع للواجهة نعيد الجدولة، فإشعار «صارلك يومين» بيتأجّل.
        #if canImport(UIKit)
        NotificationCenter.default.addObserver(
            forName: UIApplication.didBecomeActiveNotification,
            object: nil, queue: .main
        ) { _ in
            NotificationManager.shared.scheduleProactiveNudges()
        }
        #endif
    }

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

    /// لو ما في مستمع بعد، نحتفظ بالتوكن لآخر.
    func handleDeviceToken(_ deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        lastDeviceToken = hex
        onDeviceToken?(hex)
    }

    /// يرفع أي توكن وصل قبل ضبط المستمع.
    func bindDeviceToken(_ handler: @escaping (String) -> Void) {
        onDeviceToken = handler
        if let t = lastDeviceToken { handler(t) }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler:
                                    @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .list])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        // زرّ على تذكير: بيشتغل حتى لو التطبيق مش شغّال (بيقلع بالخلفية، والتوكن من الـKeychain).
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
        // الدفع البعيد للتنبيه اليومي بيحمل "kind" → الرئيسية. المحلّي بيُعرف ببادئة هويته.
        let userInfo = response.notification.request.content.userInfo
        let route: NotifRoute? = (userInfo["kind"] != nil)
            ? .dailyNudge
            : Self.route(forIdentifier: id)
        if let route {
            DispatchQueue.main.async { self.pendingRoute = route }
        }
        completionHandler()
    }

    /// nil = يفتح التطبيق بس.
    static func route(forIdentifier id: String) -> NotifRoute? {
        if id.hasPrefix(weeklyID) { return .insights }
        if id.hasPrefix(headsUpPrefix + "task.") { return .tasks }
        if id.hasPrefix(headsUpPrefix) { return .reminders }
        if id.hasPrefix("reminder.") { return .reminders }
        if id.hasPrefix("task.") { return .tasks }
        if id.hasPrefix("future.") { return .future }
        return nil
    }

    /// نلغي كل المعلّق بالبادئة ثم نجدول العناصر المستقبلية.
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
        // عناصر كل نوع، منها بتنبني تنبيهات «بعد ساعة».
        knownLock.lock()
        knownItems[prefix] = items
        knownLock.unlock()
        scheduleProactiveNudges()
    }

    /// Local notifications ring without re-checking the session, so clear everything (and
    /// `knownItems`, which nudges rebuild from) or the next account gets these reminders.
    func clearForSignOut() {
        center.removeAllPendingNotificationRequests()
        center.removeAllDeliveredNotifications()
        knownLock.lock()
        knownItems.removeAll()
        knownLock.unlock()
        onDeviceToken = nil
    }

    // MARK: - Reminder actions

    static let reminderCategory = "SANDY_REMINDER"
    /// userInfo keys the buttons read back.
    static let reminderIdKey = "reminder_id"
    static let reminderRecurrenceKey = "reminder_recurrence"
    /// «Remind me later» from the lock screen; matches the backend default.
    static let snoozeMinutes = 10

    /// Titles are baked in at registration, so this reruns on language change.
    func registerReminderCategory() {
        let lang = AppLocale.lang
        let snooze = UNNotificationAction(
            identifier: ReminderNotificationAction.snooze.rawValue,
            title: translate(lang, "blocks.notif.snooze"),
            options: [])
        let done = UNNotificationAction(
            identifier: ReminderNotificationAction.done.rawValue,
            title: translate(lang, "blocks.notif.done"),
            options: [])
        let remove = UNNotificationAction(
            identifier: ReminderNotificationAction.delete.rawValue,
            title: translate(lang, "blocks.notif.delete"),
            options: [.destructive])
        center.setNotificationCategories([
            UNNotificationCategory(identifier: Self.reminderCategory,
                                   actions: [snooze, done, remove],
                                   intentIdentifiers: [],
                                   options: [])
        ])
    }

    /// Backend first, then re-arm or leave cancelled, then tell an open reminders screen to refetch.
    /// On failure the next reminders load rebuilds notifications from the server.
    private func perform(_ action: ReminderNotificationAction,
                         reminderId: String,
                         notification: UNNotificationRequest,
                         completion: @escaping () -> Void) {
        let notifId = notification.identifier
        center.removeDeliveredNotifications(withIdentifiers: [notifId])
        center.removePendingNotificationRequests(withIdentifiers: [notifId])

        let content = notification.content
        let recurrence = content.userInfo[Self.reminderRecurrenceKey] as? String ?? ""
        let info = [Self.reminderIdKey: reminderId,
                    Self.reminderRecurrenceKey: recurrence]

        // ObservableObject: ننفّذ ع الخيط الرئيسي.
        Task { @MainActor [weak self] in
            guard let self else { completion(); return }
            let api = APIClient(baseURL: Backend.currentURL)
            do {
                switch action {
                case .snooze:
                    let at = Date().addingTimeInterval(TimeInterval(Self.snoozeMinutes * 60))
                    SchedulesStore.bannerAction(id: reminderId, movedTo: at, userId: api.currentUserId)
                    try await api.updateSchedule(id: reminderId, at: at)
                    // One shot on purpose: repeating from the snoozed time would ring late every day after.
                    self.schedule(id: notifId, title: content.title, body: content.body,
                                  at: at, category: Self.reminderCategory, userInfo: info)
                case .done:
                    // A repeating one keeps its repeating notification; a one-off is closed.
                    if recurrence.isEmpty {
                        SchedulesStore.bannerAction(id: reminderId, movedTo: nil, userId: api.currentUserId)
                        try await api.updateSchedule(id: reminderId, status: "cancelled")
                    } else {
                        // Removing it above also removed the repeat; put the same trigger back.
                        try await self.center.add(UNNotificationRequest(
                            identifier: notifId, content: content, trigger: notification.trigger))
                    }
                case .delete:
                    SchedulesStore.bannerAction(id: reminderId, movedTo: nil, userId: api.currentUserId)
                    try await api.deleteSchedule(id: reminderId)
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

    // MARK: - Proactive nudges (local)

    /// Shared root so they never collide with per-item prefixes, and reschedule replaces.
    static let proactivePrefix = "proactive."
    static let awayID = "proactive.away"
    static let weeklyID = "proactive.weekly"
    static let headsUpPrefix = "proactive.headsUp."

    /// The last items `sync` saw per prefix.
    private var knownItems: [String: [NotificationItem]] = [:]
    private let knownLock = NSLock()

    /// Safe to call often: away ping 48h ahead (pushed on each open), heads-up 60 min before
    /// today's timed items, weekly Sunday 19:00. Clears them when notifications are denied.
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

            // (a) صارلك يومين — same id, replaces the previous one.
            self.addProactive(
                id: Self.awayID,
                title: translate(lang, "blocks.notif.away.title"),
                body: translate(lang, "blocks.notif.away.body"),
                trigger: UNTimeIntervalNotificationTrigger(timeInterval: 48 * 3600, repeats: false))

            // (c) weekday 1 is Sunday in the Gregorian calendar.
            var sunday = DateComponents()
            sunday.weekday = 1
            sunday.hour = 19
            sunday.minute = 0
            self.addProactive(
                id: Self.weeklyID,
                title: translate(lang, "blocks.notif.weekly.title"),
                body: translate(lang, "blocks.notif.weekly.body"),
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
                        title: translate(lang, "blocks.notif.headsUp.title"),
                        body: String(format: translate(lang, "blocks.notif.headsUp.body"), h.text),
                        trigger: UNCalendarNotificationTrigger(dateMatching: comps, repeats: false))
                }
            }
        }
    }

    /// Skips heads-ups that are past or coincide (±1 min) with another notification.
    /// A task at 09:00 sharp means "no time" (its store's default) and is skipped.
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

    /// هوية ثابتة بتستبدل القديم. الماضي يُتجاهل.
    private func schedule(id: String, title: String, body: String, at date: Date,
                          repeats: NotificationRepeat = .none,
                          category: String? = nil,
                          userInfo: [String: String] = [:]) {
        guard date > Date() || repeats != .none else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        // الحمولة بتخلّي الزرّ ينفّذ بلا ما يفتح التطبيق.
        if let category { content.categoryIdentifier = category }
        if !userInfo.isEmpty {
            var payload: [AnyHashable: Any] = [:]
            for (key, value) in userInfo { payload[key] = value }
            content.userInfo = payload
        }
        // The matching components decide the repeat: time of day, plus weekday or day of month.
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

    /// متسامح: بمنطقة زمنية، بكسور ثانية، أو بدون. المحلّلات مبنية مرّة (غالية، وآمنة بين الخيوط).
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
    /// بدون منطقة زمنية — بالتوقيت المحلي.
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

    /// تاريخ بلا وقت — بالتوقيت المحلي.
    private static let isoDayOnly: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone.current
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    /// مثل `parseISO` بس بيقبل كمان تاريخ بلا وقت.
    static func parseISOOrDay(_ s: String) -> Date? {
        if s.isEmpty { return nil }
        return parseISO(s) ?? isoDayOnly.date(from: s)
    }
}
