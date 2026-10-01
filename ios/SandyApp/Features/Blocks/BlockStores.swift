import SwiftUI

/// The kinds table from the server, loaded once and shared: it decides which lists,
/// log kinds and labels the screens show.
@MainActor
final class KindsStore: ObservableObject {
    static let shared = KindsStore()
    @Published private(set) var kinds: [BlockKind] = []

    func load(api: APIClient) async {
        guard kinds.isEmpty, let loaded = try? await api.blockKinds() else { return }
        kinds = loaded
    }

    /// Lists the user sees; the `project:` family is not a list of its own.
    var lists: [BlockKind] { kinds.filter { $0.block == .list && $0.prefix != true } }
    /// Log kinds the user adds by hand; chat summaries are Sandy's, not the user's.
    var logKinds: [BlockKind] { kinds.filter { $0.block == .log && $0.name != "summary" } }

    func kind(_ name: String, _ block: BlockType) -> BlockKind? {
        kinds.first { $0.name == name && $0.block == block }
    }

    /// The kind, or a bare one named after it when the table has not loaded yet
    /// (a notification can open a screen before the first fetch).
    func kindOrBare(_ name: String, _ block: BlockType) -> BlockKind {
        kind(name, block) ?? BlockKind(name: name, block: block, labels: [:],
                                       icon: "circle", prefix: false)
    }
}

/// One list (tasks, shopping, goals...).
@MainActor
final class ItemsStore: LoadableStore {
    let list: String
    @Published var items: [ListItem] = []
    @Published var showDone = false
    /// Habits only: the ones checked in today (a habit is never "done", it is done today).
    @Published var checkedToday: [String: String] = [:]   // habit id → today's check-in entry id
    /// Habits only: days in a row each habit was kept, today included once it is checked.
    @Published var streaks: [String: Int] = [:]
    /// The last one ticked done, so a slip of the finger can be taken back.
    @Published var justDone: ListItem?
    private var loadTask: Task<Void, Never>?

    init(list: String) { self.list = list }

    var isHabits: Bool { list == "habits" }

    /// Habits: what is left today first, what is kept today sinks to the end.
    var ordered: [ListItem] {
        guard isHabits else { return items }
        return items.filter { checkedToday[$0.id] == nil } + items.filter { checkedToday[$0.id] != nil }
    }

    private static let day: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private var cacheKey: String { "items.\(list).\(showDone ? "done" : "open")" }

    func load(api: APIClient) async {
        loadTask?.cancel()
        let gen = beginLoad()
        // Offline: the last copy shows at once, the fetch replaces it.
        if !hasSnapshot, let cached = DiskCache.load([ListItem].self, key: cacheKey,
                                                     userId: api.currentUserId) {
            items = cached
            hasSnapshot = true
        }
        let task = Task { @MainActor in
            defer { endLoad(gen) }
            do {
                let rows = try await api.listItems(list, done: showDone)
                let checks = isHabits ? try await checkIns(api: api) : ([:], [:])
                guard isCurrentLoad(gen) else { return }
                items = rows
                (checkedToday, streaks) = checks
                markLoaded()
                DiskCache.save(rows, key: cacheKey, userId: api.currentUserId)
                if !showDone {
                    publishTasks()
                    SpotlightIndexer.indexItems(list: list, rows)
                }
            } catch {
                failLoad(error, generation: gen) { notify("blocks.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    func add(api: APIClient, text: String, due: Date? = nil, priority: String? = nil) async {
        do {
            try await api.addItem(list: list, text: text, due: due, priority: priority)
            clearNotice()
            await load(api: api)
        } catch {
            notify("blocks.errorSave")
        }
    }

    /// Today's check-ins (habit id → entry id) and each habit's run of days.
    private func checkIns(api: APIClient) async throws -> ([String: String], [String: Int]) {
        let cal = Calendar.current
        let today = Self.day.string(from: Date())
        var todays: [String: String] = [:]
        var days: [String: Set<String>] = [:]
        for e in try await api.entries(kind: "habit", limit: 1000) {
            guard case .string(let date)? = e.data?["date"],
                  case .string(let habit)? = e.data?["habit_item_id"] else { continue }
            days[habit, default: []].insert(date)
            if date == today { todays[habit] = e.id }
        }
        var streaks: [String: Int] = [:]
        for (habit, set) in days {
            // A run still counts while today is not checked yet: it starts from yesterday.
            var day = set.contains(today) ? Date() : cal.date(byAdding: .day, value: -1, to: Date())!
            var n = 0
            while set.contains(Self.day.string(from: day)) {
                n += 1
                day = cal.date(byAdding: .day, value: -1, to: day)!
            }
            streaks[habit] = n
        }
        return (todays, streaks)
    }

    func toggle(api: APIClient, _ item: ListItem) {
        if isHabits { return checkIn(api: api, item) }
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        let removed = items[idx]
        if !item.done { justDone = item }
        // It leaves this filter (open ↔ done), so it leaves the list.
        optimistic("blocks.errorSave",
                   apply: { self.items.remove(at: idx); self.publishTasks() },
                   rollback: { self.items.insert(removed, at: min(idx, self.items.count)); self.publishTasks() },
                   call: { try await api.updateItem(id: item.id, done: !item.done) })
    }

    /// Puts the last ticked one back as open.
    func undoDone(api: APIClient) {
        guard let item = justDone else { return }
        justDone = nil
        optimistic("blocks.errorSave",
                   apply: { self.items.insert(item, at: 0); self.publishTasks() },
                   rollback: { self.items.removeAll { $0.id == item.id }; self.publishTasks() },
                   call: { try await api.updateItem(id: item.id, done: false) })
    }

    /// Saves an edit in place; the row changes at once and comes back if the server refuses.
    func update(api: APIClient, _ item: ListItem, text: String, due: Date?, important: Bool) {
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        let old = items[idx]
        var new = old
        new.text = text
        let priority = isHabits ? nil : (important ? "high" : "normal")
        var change = APIClient.ItemChange()
        if text != old.text { change.text = text }
        if !isHabits {
            new.priority = priority
            if priority != (old.priority ?? "normal") { change.priority = priority }
            let oldDue = NotificationManager.parseISOOrDay(old.due ?? "")
            if due != oldDue {
                change.due = .some(due)
                new.due = due.map { ISO8601DateFormatter().string(from: $0) }
            }
        }
        optimistic("blocks.errorSave",
                   apply: { self.items[idx] = new; self.publishTasks() },
                   rollback: {
                       if let i = self.items.firstIndex(where: { $0.id == item.id }) { self.items[i] = old }
                       self.publishTasks()
                   },
                   call: { try await api.updateItem(id: item.id, change) })
    }

    func delete(api: APIClient, _ item: ListItem) {
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        let removed = items[idx]
        optimistic("blocks.errorSave",
                   apply: { self.items.remove(at: idx) },
                   rollback: { self.items.insert(removed, at: min(idx, self.items.count)) },
                   call: { try await api.deleteItem(id: item.id) })
    }

    /// Check in today (a `habit` log entry), or undo today's check-in.
    private func checkIn(api: APIClient, _ item: ListItem) {
        if let entry = checkedToday[item.id] {
            let streak = streaks[item.id] ?? 0
            optimistic("blocks.errorSave",
                       apply: { self.checkedToday[item.id] = nil; self.streaks[item.id] = max(streak - 1, 0) },
                       rollback: { self.checkedToday[item.id] = entry; self.streaks[item.id] = streak },
                       call: { try await api.deleteEntry(id: entry) })
            return
        }
        let streak = streaks[item.id] ?? 0
        checkedToday[item.id] = ""
        streaks[item.id] = streak + 1
        Task { @MainActor in
            do {
                try await api.addEntry(kind: "habit", text: item.text, data: [
                    "habit_item_id": .string(item.id),
                    "date": .string(Self.day.string(from: Date()))])
                (checkedToday, streaks) = try await checkIns(api: api)
            } catch {
                checkedToday[item.id] = nil
                streaks[item.id] = streak
                notify("blocks.errorSave")
            }
        }
    }

    /// Tasks feed the home-screen widget and their due-time notifications.
    private func publishTasks() {
        guard list == "tasks" else { return }
        let open = items.filter { !$0.done }
        let tasks = open.map { TaskItem(id: $0.id, text: $0.text, done: false,
                                        dueAt: $0.due ?? "", priority: $0.priority ?? "normal") }
        WidgetData.setOpenTasks(tasks)
        WidgetData.setActiveTasks(count: tasks.count)
        let title = AppLocale.isArabic ? "مهمة" : "Task"
        let notes = open.compactMap { item -> NotificationItem? in
            guard let date = NotificationManager.parseISO(item.due ?? ""), date > Date() else { return nil }
            return NotificationItem(id: item.id, title: title, body: item.text, date: date)
        }
        NotificationManager.shared.sync(prefix: "task.", items: notes)
    }
}

/// Upcoming reminders; the phone rings them as local notifications.
@MainActor
final class SchedulesStore: LoadableStore {
    let kind: String
    @Published var items: [ScheduleItem] = []

    init(kind: String = "reminder") { self.kind = kind }

    func load(api: APIClient) async {
        let gen = beginLoad()
        defer { endLoad(gen) }
        let cacheKey = "schedules.\(kind)"
        if !hasSnapshot, let cached = DiskCache.load([ScheduleItem].self, key: cacheKey,
                                                     userId: api.currentUserId) {
            items = cached
            hasSnapshot = true
        }
        do {
            let rows = try await api.schedules(kind: kind)
            guard isCurrentLoad(gen) else { return }
            items = rows.sorted { $0.fireAt < $1.fireAt }
            markLoaded()
            DiskCache.save(items, key: cacheKey, userId: api.currentUserId)
            publish()
            if kind == "reminder" { SpotlightIndexer.indexReminders(items) }
        } catch {
            failLoad(error, generation: gen) { notify("blocks.errorLoad") }
        }
    }

    func add(api: APIClient, text: String, at: Date, recurrence: String?) async -> Bool {
        do {
            try await api.addSchedule(kind: kind, text: text, at: at, recurrence: recurrence)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("blocks.errorSave")
            return false
        }
    }

    func delete(api: APIClient, _ item: ScheduleItem) {
        drop(item) { try await api.deleteSchedule(id: item.id) }
    }

    /// Already done: a one-off is closed. A repeating one stays for its next time.
    func complete(api: APIClient, _ item: ScheduleItem) {
        drop(item) { try await api.updateSchedule(id: item.id, status: "cancelled") }
    }

    /// Takes it off the list now and puts it back if the server refuses.
    private func drop(_ item: ScheduleItem, call: @escaping () async throws -> Void) {
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        let removed = items[idx]
        optimistic("blocks.errorSave",
                   apply: { self.items.remove(at: idx); self.publish() },
                   rollback: { self.items.insert(removed, at: min(idx, self.items.count)); self.publish() },
                   call: call)
    }

    /// Edit text, time or repeat; recurrence "" makes it ring once.
    func update(api: APIClient, _ item: ScheduleItem, text: String, at: Date, recurrence: String?) async -> Bool {
        let moved = NotificationManager.parseISO(item.fireAt).map { abs($0.timeIntervalSince(at)) >= 60 } ?? true
        do {
            try await api.updateSchedule(id: item.id, at: moved ? at : nil,
                                         text: text == item.text ? nil : text,
                                         recurrence: recurrence ?? "")
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("blocks.errorSave")
            return false
        }
    }

    private func sortByTime() {
        items.sort {
            (NotificationManager.parseISO($0.fireAt) ?? .distantFuture)
                < (NotificationManager.parseISO($1.fireAt) ?? .distantFuture)
        }
    }

    /// Later: the same reminder, `minutes` from now.
    func snooze(api: APIClient, _ item: ScheduleItem, minutes: Int) {
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        let old = items[idx]
        let at = Date().addingTimeInterval(TimeInterval(minutes * 60))
        var new = old
        new.fireAt = ISO8601DateFormatter().string(from: at)
        optimistic("blocks.errorSave",
                   apply: {
                       self.items[idx] = new
                       self.sortByTime()
                       self.publish()
                   },
                   rollback: {
                       if let i = self.items.firstIndex(where: { $0.id == item.id }) { self.items[i] = old }
                       self.sortByTime()
                       self.publish()
                   },
                   call: { try await api.updateSchedule(id: item.id, at: at) })
    }

    private func publish() {
        // Only reminders ring on the phone; a message to future self arrives in chat.
        guard kind == "reminder" else { return }
        let title = AppLocale.isArabic ? "تذكير" : "Reminder"
        let notes = items.compactMap { s -> NotificationItem? in
            guard let date = NotificationManager.parseISO(s.fireAt) else { return nil }
            let rule = s.recurrence ?? ""
            // The category puts «later / done / delete» on the banner; the info lets them act
            // while the app is closed.
            return NotificationItem(id: s.id, title: title, body: s.text, date: date,
                                    repeats: NotificationRepeat(rrule: rule),
                                    category: NotificationManager.reminderCategory,
                                    userInfo: [NotificationManager.reminderIdKey: s.id,
                                               NotificationManager.reminderRecurrenceKey: rule])
        }
        // Same prefix the old reminders used, so their notifications are replaced, not doubled.
        NotificationManager.shared.sync(prefix: "reminder.", items: notes)
        let next = items.first
        WidgetData.setNextReminder(text: next?.text,
                                   date: next.flatMap { NotificationManager.parseISO($0.fireAt) })
    }
}

/// The log: everything that happened, newest first, optionally one kind.
@MainActor
final class LogStore: LoadableStore {
    @Published var entries: [LogEntry] = []
    @Published var kind: String?

    init(kind: String? = nil) { self.kind = kind }

    func load(api: APIClient) async {
        let gen = beginLoad()
        defer { endLoad(gen) }
        let cacheKey = "entries.\(kind ?? "all")"
        if !hasSnapshot, let cached = DiskCache.load([LogEntry].self, key: cacheKey,
                                                     userId: api.currentUserId) {
            entries = cached
            hasSnapshot = true
        }
        do {
            let rows = try await api.entries(kind: kind)
            guard isCurrentLoad(gen) else { return }
            entries = rows
            markLoaded()
            DiskCache.save(entries, key: cacheKey, userId: api.currentUserId)
            if kind == nil { SpotlightIndexer.indexEntries(entries) }
        } catch {
            failLoad(error, generation: gen) { notify("blocks.errorLoad") }
        }
    }

    func add(api: APIClient, kind: String, text: String, amount: Double?, at: Date? = nil) async -> Bool {
        do {
            try await api.addEntry(kind: kind, text: text,
                                   data: amount.map { ["amount": .number($0)] }, at: at)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("blocks.errorSave")
            return false
        }
    }

    /// Edit text, amount or time; the amount goes into a copy of the row's data.
    func update(api: APIClient, _ entry: LogEntry, text: String, amount: Double?, at: Date) {
        guard let idx = entries.firstIndex(where: { $0.id == entry.id }) else { return }
        let old = entries[idx]
        var new = old
        new.text = text
        var data: [String: JSONValue]?
        if entry.kind == "expense" {
            var d = old.data ?? [:]
            d["amount"] = amount.map { JSONValue.number($0) }
            data = d
            new.data = d
        }
        let moved = NotificationManager.parseISO(old.at ?? "").map { abs($0.timeIntervalSince(at)) >= 60 } ?? true
        if moved { new.at = ISO8601DateFormatter().string(from: at) }
        optimistic("blocks.errorSave",
                   apply: { self.entries[idx] = new },
                   rollback: {
                       if let i = self.entries.firstIndex(where: { $0.id == entry.id }) { self.entries[i] = old }
                   },
                   call: { try await api.updateEntry(id: entry.id, text: text == old.text ? nil : text,
                                                     data: data, at: moved ? at : nil) })
    }

    func delete(api: APIClient, _ entry: LogEntry) {
        guard let idx = entries.firstIndex(where: { $0.id == entry.id }) else { return }
        let removed = entries[idx]
        optimistic("blocks.errorSave",
                   apply: { self.entries.remove(at: idx) },
                   rollback: { self.entries.insert(removed, at: min(idx, self.entries.count)) },
                   call: { try await api.deleteEntry(id: entry.id) })
    }
}
