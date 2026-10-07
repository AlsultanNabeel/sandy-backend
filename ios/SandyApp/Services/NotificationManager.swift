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
    /// Rings like an alarm: its own long sound, and again if unanswered.
    var alarm = false
    /// The alarm passes a Focus and quiet hours (chosen per alarm).
    var breaksFocus = false
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

/// What the manager asks of the system's notification center; tests hand it one that only
/// records.
protocol NotificationScheduler: AnyObject {
    var delegate: UNUserNotificationCenterDelegate? { get set }
    func add(_ request: UNNotificationRequest, withCompletionHandler completionHandler: ((Error?) -> Void)?)
    func getPendingNotificationRequests(completionHandler: @escaping ([UNNotificationRequest]) -> Void)
    func removePendingNotificationRequests(withIdentifiers identifiers: [String])
    func removeDeliveredNotifications(withIdentifiers identifiers: [String])
    func removeAllPendingNotificationRequests()
    func removeAllDeliveredNotifications()
    func setNotificationCategories(_ categories: Set<UNNotificationCategory>)
    /// The user lets the app notify (allowed, provisional or ephemeral).
    func notificationsAllowed(_ done: @escaping (Bool) -> Void)
}

extension UNUserNotificationCenter: NotificationScheduler {
    func notificationsAllowed(_ done: @escaping (Bool) -> Void) {
        getNotificationSettings { settings in
            done([.authorized, .provisional, .ephemeral].contains(settings.authorizationStatus))
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
    /// The system's center; a test swaps in its own.
    var center: NotificationScheduler = UNUserNotificationCenter.current()

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
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
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
        // Answered: an alarm's follow-up rings are not needed any more.
        clearAgain(response.notification.request.identifier)
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

        let route = Self.route(kind: response.notification.request.content.userInfo["kind"] as? String,
                               identifier: response.notification.request.identifier)
        if let route {
            DispatchQueue.main.async { self.pendingRoute = route }
        }
        completionHandler()
    }

    /// A server push carries its `kind` (a reminder opens the reminders, anything else Today);
    /// a local one is known by its id's prefix. nil = just opens the app.
    static func route(kind: String?, identifier: String) -> NotifRoute? {
        if kind == "reminder" { return .reminders }
        if kind != nil { return .dailyNudge }
        return route(forIdentifier: identifier)
    }

    private static func route(forIdentifier id: String) -> NotifRoute? {
        if id.hasPrefix(weeklyID) { return .insights }
        if id.hasPrefix(headsUpPrefix + "task.") { return .tasks }
        if id.hasPrefix(headsUpPrefix) { return .reminders }
        if id.hasPrefix("reminder.") { return .reminders }
        if id.hasPrefix("task.") { return .tasks }
        if id.hasPrefix("future.") { return .future }
        return nil
    }

    /// What Profile › Notifications calls «reminders»: reminders, timed tasks, habits.
    private static let reminderPrefixes: Set<String> = ["reminder.", "task.", "habit."]

    /// This kind's items are now `items`: everything known is scheduled again. Nothing with
    /// no one signed in.
    func sync(prefix: String, items: [NotificationItem]) {
        guard isSignedIn else { return }
        // عناصر كل نوع، منها بتنبني تنبيهات «بعد ساعة».
        knownLock.lock()
        knownItems[prefix] = items
        knownLock.unlock()
        rearm()
        scheduleProactiveNudges()
    }

    /// Requests the items may take: the system keeps sixty-four and drops the rest without a
    /// word, and the nudges, the heads-ups and an alert now need the others.
    static let itemBudget = 50
    static let headsUpLimit = 6

    /// Replaces the pending requests of every kind known in this run with its items, the
    /// nearest first while they fit under `itemBudget` (an alarm takes three; a kind not
    /// reported yet, after a launch with no screen, is left as it is and counted). Switched
    /// off in Profile › Notifications, nothing of these kinds rings (they stay known, so
    /// turning it back on brings them back). Then the server hears which reminders are armed.
    private func rearm() {
        knownLock.lock()
        let known = knownItems
        knownLock.unlock()
        let now = Date()
        let candidates = (NotificationPrefs.current.reminders ? known : [:])
            .filter { Self.reminderPrefixes.contains($0.key) }
            .flatMap { prefix, items in
                items.compactMap { raw -> (id: String, item: NotificationItem, next: Date)? in
                    let it = prefix == "reminder." ? Self.firstRing(raw, after: now) : raw
                    return Self.nextRing(it, after: now).map { (prefix + it.id, it, $0) }
                }
            }
            .sorted { $0.next < $1.next }
        // Repeats held here as their first ring only.
        let once = Set(candidates.filter { $0.item.repeats == .none }.map(\.item.id))
            .intersection((known["reminder."] ?? []).filter { $0.repeats != .none }.map(\.id))
        center.getPendingNotificationRequests { [weak self] reqs in
            guard let self else { return }
            let ids = reqs.map(\.identifier)
            let stale = ids.filter { id in known.keys.contains { id.hasPrefix($0) } }
            let others = ids.filter { id in
                !stale.contains(id) && Self.reminderPrefixes.contains { id.hasPrefix($0) }
            }.count
            var left = Self.itemBudget - others
            var wanted: [(String, NotificationItem)] = []
            for c in candidates {
                let cost = c.item.alarm && c.item.repeats == .none ? 1 + Self.alarmAgainCount : 1
                guard cost <= left else { continue }
                left -= cost
                wanted.append((c.id, c.item))
            }
            self.center.removePendingNotificationRequests(withIdentifiers: stale)
            for (id, it) in wanted {
                self.schedule(id: id, title: it.title, body: it.body,
                              at: it.date, repeats: it.repeats,
                              category: it.category, userInfo: it.userInfo,
                              alarm: it.alarm, breaksFocus: it.breaksFocus)
            }
            // Only what was really scheduled: the server pushes the rest.
            self.center.getPendingNotificationRequests { now in
                let armed = Set(now.map(\.identifier).filter { $0.hasPrefix("reminder.") }
                    .map { String(Self.baseId($0).dropFirst("reminder.".count)) })
                if known["reminder."] != nil {
                    self.reportArmed(armed.sorted(), once: armed.intersection(once).sorted())
                }
            }
        }
    }

    // MARK: - Armed reminders (the server pushes the others)

    /// The client the set is sent with, and the pause that gathers a burst of syncs into one
    /// report; tests set both.
    var armingAPI: () -> APIClient = { APIClient(baseURL: Backend.currentURL) }
    static var armDelay: UInt64 = 1_000_000_000
    private var armTask: Task<Void, Never>?
    /// The last set (and its repeats held for one ring), sent again once the push token is
    /// registered.
    private var armedIds: (ids: [String], once: [String])?

    /// `POST /api/schedules/armed` with this phone's whole set; only the newest matters, so
    /// it is not queued, and with no push token there is nothing to tell.
    private func reportArmed(_ ids: [String], once: [String]) {
        DispatchQueue.main.async {
            self.armedIds = (ids, once)
            self.armTask?.cancel()
            guard let token = self.lastDeviceToken, self.isSignedIn else { return }
            let api = self.armingAPI()
            self.armTask = Task { @MainActor in
                try? await Task.sleep(nanoseconds: Self.armDelay)
                guard !Task.isCancelled else { return }
                try? await api.reportArmed(token: token, ids: ids, once: once)
            }
        }
    }

    /// The push token reached the server: the set waiting for it goes now.
    @MainActor
    func pushTokenRegistered() {
        if let set = armedIds { reportArmed(set.ids, once: set.once) }
    }

    /// Signing out: the server hears this phone holds none, then forgets its token (both
    /// with the session that is ending), so it pushes again instead of counting on it.
    @MainActor
    func leave(api: APIClient, bearer: String) async {
        armTask?.cancel()
        armedIds = nil
        guard let token = lastDeviceToken else { return }
        try? await api.reportArmed(token: token, ids: [], once: [], bearer: bearer)
        try? await api.unregisterPushToken(token, bearer: bearer)
    }

    /// Local notifications ring without re-checking the session, so clear everything (and
    /// `knownItems`, which nudges rebuild from) or the next account gets these reminders.
    func clearForSignOut() {
        knownLock.lock()
        signedIn = false
        knownItems.removeAll()
        openTasks = 0
        habitsLeft = []
        habitsTotal = 0
        knownLock.unlock()
        center.removeAllPendingNotificationRequests()
        center.removeAllDeliveredNotifications()
        onDeviceToken = nil
        DispatchQueue.main.async {
            self.armTask?.cancel()
            self.armedIds = nil
        }
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
        let notifId = Self.baseId(notification.identifier)
        center.removeDeliveredNotifications(withIdentifiers: [notifId])
        center.removePendingNotificationRequests(withIdentifiers: [notifId])

        let content = notification.content
        let recurrence = content.userInfo[Self.reminderRecurrenceKey] as? String ?? ""
        let alarm = content.userInfo[Self.alarmKey] as? String == "1"
        let breaksFocus = content.userInfo[Self.focusKey] as? String == "1"
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
                                  at: at, category: Self.reminderCategory, userInfo: info,
                                  alarm: alarm, breaksFocus: breaksFocus)
                case .done:
                    // A repeating one keeps its repeating notification; a one-off is closed.
                    if recurrence.isEmpty {
                        SchedulesStore.bannerAction(id: reminderId, movedTo: nil, userId: api.currentUserId)
                        try await api.updateSchedule(id: reminderId, status: "cancelled")
                    } else {
                        // Removing it above also removed the repeat; put the same trigger back.
                        self.center.add(UNNotificationRequest(
                            identifier: notifId, content: content, trigger: notification.trigger),
                                        withCompletionHandler: nil)
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
    static let morningID = "proactive.morning"
    static let habitsID = "proactive.habits"

    /// What the morning and evening nudges talk about, from the stores.
    private var openTasks = 0
    private var habitsLeft: [String] = []
    private var habitsTotal = 0
    private var signedIn = false

    /// What the morning and evening nudges would say now; nil with no one signed in.
    func nudgeInputs() -> (tasks: Int, habitsLeft: [String], habits: Int)? {
        knownLock.lock()
        defer { knownLock.unlock() }
        return signedIn ? (openTasks, habitsLeft, habitsTotal) : nil
    }

    /// A session began: the stores' counts and items are scheduled from now on. Until then,
    /// and after `clearForSignOut`, nothing is (the sign-in screen must not ring the last
    /// account's habit names on the lock screen).
    func sessionBegan() {
        knownLock.lock()
        signedIn = true
        knownLock.unlock()
    }

    private var isSignedIn: Bool {
        knownLock.lock()
        defer { knownLock.unlock() }
        return signedIn
    }

    func setOpenTasks(_ count: Int) {
        knownLock.lock()
        guard signedIn else { knownLock.unlock(); return }
        openTasks = count
        knownLock.unlock()
        scheduleProactiveNudges()
    }

    func setHabits(left: [String], total: Int) {
        knownLock.lock()
        guard signedIn else { knownLock.unlock(); return }
        habitsLeft = left
        habitsTotal = total
        knownLock.unlock()
        scheduleProactiveNudges()
    }

    /// The last items `sync` saw per prefix.
    private var knownItems: [String: [NotificationItem]] = [:]
    private let knownLock = NSLock()

    /// Safe to call often: away ping 48h ahead (pushed on each open), heads-up 60 min before
    /// today's timed items, weekly Friday 19:00. Clears them when notifications are denied.
    /// Profile › Notifications changed: everything the phone rings is scheduled again.
    func preferencesChanged() {
        knownLock.lock()
        let anything = !knownItems.isEmpty
        knownLock.unlock()
        if anything && isSignedIn { rearm() }
        scheduleProactiveNudges()
    }

    func scheduleProactiveNudges() {
        guard let (tasks, left, habitCount) = nudgeInputs() else { return }
        knownLock.lock()
        let known = knownItems
        knownLock.unlock()
        center.notificationsAllowed { [weak self] allowed in
            guard let self else { return }
            // Denied, or proactive nudges switched off in Profile › Notifications.
            guard allowed, NotificationPrefs.current.proactive else {
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

            // (c) the week runs Saturday to Friday: asked on its last evening.
            // Weekday 6 is Friday in the Gregorian calendar.
            var friday = DateComponents()
            friday.weekday = 6
            friday.hour = 19
            friday.minute = 0
            self.addProactive(
                id: Self.weeklyID,
                title: translate(lang, "blocks.notif.weekly.title"),
                body: translate(lang, "blocks.notif.weekly.body"),
                trigger: UNCalendarNotificationTrigger(dateMatching: friday, repeats: true))

            // (d) good morning with the day in one line, the next 8:30.
            let morning = Self.next(hour: 8, minute: 30)
            let reminders = (known["reminder."] ?? []).filter {
                $0.repeats == .daily || Calendar.current.isDate($0.date, inSameDayAs: morning)
            }.count
            let busy = tasks + reminders + habitCount > 0
            self.addProactive(
                id: Self.morningID,
                title: translate(lang, "blocks.notif.morning.title"),
                body: busy ? String(format: translate(lang, "blocks.notif.morning.body"),
                                    AppLocale.number(tasks), AppLocale.number(reminders),
                                    AppLocale.number(habitCount))
                           : translate(lang, "blocks.notif.morning.free"),
                trigger: Self.at(morning))

            // (e) at nine in the evening, the habits not kept yet today.
            let evening = Calendar.current.date(bySettingHour: 21, minute: 0, second: 0, of: Date()) ?? Date()
            if left.isEmpty || evening <= Date() {
                self.center.removePendingNotificationRequests(withIdentifiers: [Self.habitsID])
            } else {
                self.addProactive(
                    id: Self.habitsID,
                    title: translate(lang, "blocks.notif.habits.title"),
                    body: String(format: translate(lang, "blocks.notif.habits.body"),
                                 left.prefix(3).joined(separator: lang == .ar ? "، " : ", ")),
                    trigger: Self.at(evening))
            }

            // (b) heads-up an hour before today's timed tasks/reminders.
            let heads = Self.headsUps(known: known, now: Date())
            let wanted = Set(heads.map(\.id))
            self.center.getPendingNotificationRequests { reqs in
                let stale = reqs.map(\.identifier).filter {
                    $0.hasPrefix(Self.headsUpPrefix) && !wanted.contains($0)
                }
                self.center.removePendingNotificationRequests(withIdentifiers: stale)
                for h in heads {
                    // An hour before a moment: a moment too.
                    let comps = Calendar.current.dateComponents(
                        [.timeZone, .year, .month, .day, .hour, .minute], from: h.date)
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
        return Array(out.sorted { $0.date < $1.date }.prefix(headsUpLimit))
    }

    /// Today at that time, or tomorrow when it has passed.
    private static func next(hour: Int, minute: Int) -> Date {
        let cal = Calendar.current
        let today = cal.date(bySettingHour: hour, minute: minute, second: 0, of: Date()) ?? Date()
        return today > Date() ? today : cal.date(byAdding: .day, value: 1, to: today) ?? today
    }

    private static func at(_ date: Date) -> UNCalendarNotificationTrigger {
        UNCalendarNotificationTrigger(
            dateMatching: Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: date),
            repeats: false)
    }

    private struct HeadsUp {
        let id: String
        let text: String
        let date: Date
    }

    /// Rings now (a second from now), e.g. the budget passing its mark; one of Sandy's
    /// nudges, so not with them switched off or no one signed in.
    func notifyNow(title: String, body: String) {
        guard isSignedIn, NotificationPrefs.current.proactive else { return }
        addProactive(id: Self.proactivePrefix + "now." + UUID().uuidString, title: title, body: body,
                     trigger: UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false))
    }

    private func addProactive(id: String, title: String, body: String,
                              trigger: UNNotificationTrigger) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        Self.applyQuiet(content, at: (trigger as? UNCalendarNotificationTrigger)?.nextTriggerDate()
                        ?? (trigger as? UNTimeIntervalNotificationTrigger)?.nextTriggerDate())
        center.add(UNNotificationRequest(identifier: id, content: content, trigger: trigger),
                   withCompletionHandler: nil)
    }

    /// هوية ثابتة بتستبدل القديم. الماضي يُتجاهل.
    private func schedule(id: String, title: String, body: String, at date: Date,
                          repeats: NotificationRepeat = .none,
                          category: String? = nil,
                          userInfo: [String: String] = [:],
                          alarm: Bool = false, breaksFocus: Bool = false) {
        guard date > Date() || repeats != .none else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        var info = userInfo
        // An alarm keeps to a Focus and the quiet hours like anything else, unless this alarm
        // was set to pass them (time-sensitive).
        let silenced = !(alarm && breaksFocus) && NotificationPrefs.current.isQuiet(date)
        if alarm {
            info[Self.alarmKey] = "1"
            if breaksFocus { info[Self.focusKey] = "1" }
        }
        if alarm && !silenced {
            content.sound = UNNotificationSound(named: Self.alarmSound)
            content.interruptionLevel = breaksFocus ? .timeSensitive : .active
        } else {
            Self.applyQuiet(content, at: date)
        }
        // الحمولة بتخلّي الزرّ ينفّذ بلا ما يفتح التطبيق.
        if let category { content.categoryIdentifier = category }
        if !info.isEmpty {
            var payload: [AnyHashable: Any] = [:]
            for (key, value) in info { payload[key] = value }
            content.userInfo = payload
        }
        if alarm && !silenced && repeats == .none {
            // Unanswered, it rings again, twice, a couple of minutes apart.
            for n in 1...Self.alarmAgainCount {
                let later = date.addingTimeInterval(TimeInterval(n * Self.alarmAgainMinutes * 60))
                let again = UNTimeIntervalNotificationTrigger(timeInterval: later.timeIntervalSinceNow,
                                                              repeats: false)
                center.add(UNNotificationRequest(identifier: id + Self.againSuffix + String(n),
                                                 content: content, trigger: again),
                           withCompletionHandler: nil)
            }
        }
        center.add(UNNotificationRequest(identifier: id, content: content,
                                         trigger: Self.trigger(at: date, repeats: repeats)),
                   withCompletionHandler: nil)
    }

    /// The matching components decide the repeat: time of day, plus weekday or day of month.
    /// A one-off is a moment (it keeps it across a zone change, like the server's); a repeat
    /// is a time on whatever clock the phone is on (the server moves it the same way).
    private static func trigger(at date: Date, repeats: NotificationRepeat) -> UNCalendarNotificationTrigger {
        let fields: Set<Calendar.Component>
        switch repeats {
        case .none:    fields = [.timeZone, .year, .month, .day, .hour, .minute]
        case .daily:   fields = [.hour, .minute]
        case .weekly:  fields = [.weekday, .hour, .minute]
        case .monthly: fields = [.day, .hour, .minute]
        }
        return UNCalendarNotificationTrigger(dateMatching: Calendar.current.dateComponents(fields, from: date),
                                             repeats: repeats != .none)
    }

    /// A repeat whose first time is later than its trigger would first match (a daily one
    /// that starts next Monday) rings that first time as a one-off; the next sync after it
    /// rings, by then within one repeat of now, schedules the repeat itself.
    private static func firstRing(_ item: NotificationItem, after now: Date) -> NotificationItem {
        guard item.repeats != .none, item.date > now,
              let natural = trigger(at: item.date, repeats: item.repeats).nextTriggerDate(),
              natural < item.date.addingTimeInterval(-60) else { return item }
        var first = item
        first.repeats = .none
        return first
    }

    /// When it would ring next; nil for a one-off already past.
    private static func nextRing(_ item: NotificationItem, after now: Date) -> Date? {
        if item.repeats == .none { return item.date > now ? item.date : nil }
        return trigger(at: item.date, repeats: item.repeats).nextTriggerDate()
    }

    // MARK: - Alarms

    static let alarmKey = "alarm"
    static let focusKey = "alarm_focus"
    /// A bundled ringing tone (under 30 seconds, the system's limit for a notification sound).
    static let alarmSound = UNNotificationSoundName("sandy_alarm.caf")
    static let alarmAgainCount = 2
    static let alarmAgainMinutes = 2
    private static let againSuffix = ".again"

    /// The alarm a follow-up ring belongs to.
    static func baseId(_ id: String) -> String {
        guard let r = id.range(of: againSuffix) else { return id }
        return String(id[..<r.lowerBound])
    }

    private func clearAgain(_ id: String) {
        let base = Self.baseId(id)
        let ids = (1...Self.alarmAgainCount).map { base + Self.againSuffix + String($0) }
        center.removePendingNotificationRequests(withIdentifiers: ids)
        center.removeDeliveredNotifications(withIdentifiers: ids + [base])
    }

    /// Sound, unless it rings inside the user's quiet hours: then it arrives silently
    /// (no sound, the screen stays dark) and waits in Notification Center.
    private static func applyQuiet(_ content: UNMutableNotificationContent, at date: Date?) {
        if let date, NotificationPrefs.current.isQuiet(date) {
            content.sound = nil
            content.interruptionLevel = .passive
        } else {
            content.sound = .default
        }
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
