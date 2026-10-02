import SwiftUI

// The block stores. Each one shows its last copy at once (from disk), applies every change
// on the phone first and saves it, and sends it through the outbox. A change made in one
// screen reaches every other copy of the same rows: the stores showing them now, or their
// file on disk. So with no network every tab still opens on the latest state.

/// The kinds table from the server, shared: it decides which lists, log kinds and labels
/// the screens show. Kept on disk so the screens have their names offline.
@MainActor
final class KindsStore: ObservableObject {
    static let shared = KindsStore()
    @Published private(set) var kinds: [BlockKind] = []

    func load(api: APIClient) async {
        if kinds.isEmpty, let cached = DiskCache.load([BlockKind].self, key: "kinds",
                                                      userId: api.currentUserId) {
            kinds = cached
        }
        guard let loaded = try? await api.blockKinds(), !loaded.isEmpty else { return }
        kinds = loaded
        DiskCache.save(loaded, key: "kinds", userId: api.currentUserId)
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

/// The stores alive right now, held weakly.
@MainActor
final class LiveStores<S: AnyObject> {
    private struct Box { weak var store: S? }
    private var boxes: [Box] = []

    func add(_ store: S) {
        boxes.removeAll { $0.store == nil }
        boxes.append(Box(store: store))
    }

    var all: [S] { boxes.compactMap(\.store) }
}

/// Rows of one cached list: edits the stores showing it, else its file on disk.
@MainActor
private func editCopies<S: AnyObject, T: Codable>(
    _ stores: [S], rows: ReferenceWritableKeyPath<S, [T]>, key: String, userId: String?,
    _ change: (inout [T]) -> Void
) {
    if stores.isEmpty {
        guard var cached = DiskCache.load([T].self, key: key, userId: userId) else { return }
        change(&cached)
        DiskCache.save(cached, key: key, userId: userId)
    } else {
        for store in stores { change(&store[keyPath: rows]) }
    }
}

private let isoOut = ISO8601DateFormatter()

/// Local day string, the habit check-in's `date`.
private let dayFormat: DateFormatter = {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.dateFormat = "yyyy-MM-dd"
    return f
}()

// MARK: - Lists

/// One list (tasks, shopping, goals...), its open rows or its done ones.
@MainActor
final class ItemsStore: LoadableStore {
    private static let live = LiveStores<ItemsStore>()

    let list: String
    let done: Bool
    @Published var items: [ListItem] = [] { didSet { saveItems() } }
    /// Habits only: the ones checked in today (a habit is never "done", it is done today).
    @Published var checkedToday: [String: String] = [:] { didSet { saveChecks() } }  // habit → entry id
    /// Habits only: days in a row each habit was kept, today included once it is checked.
    @Published var streaks: [String: Int] = [:] { didSet { saveChecks() } }
    /// The last one ticked done, so a slip of the finger can be taken back.
    @Published var justDone: ListItem?
    private var userId: String?
    private var restored = false
    private var loadTask: Task<Void, Never>?

    init(list: String, done: Bool = false) {
        self.list = list
        self.done = done
        super.init()
        Self.live.add(self)
    }

    var isHabits: Bool { list == "habits" }

    /// Habits: what is left today first, what is kept today sinks to the end.
    var ordered: [ListItem] {
        guard isHabits else { return items }
        return items.filter { checkedToday[$0.id] == nil } + items.filter { checkedToday[$0.id] != nil }
    }

    private static func key(_ list: String, _ done: Bool) -> String {
        "items.\(list).\(done ? "done" : "open")"
    }

    private struct Checks: Codable {
        let day: String
        let checked: [String: String]
        let streaks: [String: Int]
    }

    /// The last copy from disk, once; a new day starts with nothing checked.
    private func restore(_ api: APIClient) {
        guard !restored else { return }
        userId = api.currentUserId
        if let cached = DiskCache.load([ListItem].self, key: Self.key(list, done), userId: userId) {
            items = cached
            hasSnapshot = true
        }
        if isHabits, let c = DiskCache.load(Checks.self, key: "habits.checks", userId: userId) {
            streaks = c.streaks
            if c.day == dayFormat.string(from: Date()) { checkedToday = c.checked }
        }
        restored = true
    }

    private func saveItems() {
        guard restored else { return }
        DiskCache.save(items, key: Self.key(list, done), userId: userId)
        if list == "tasks" && !done { publishTasks() }
        if isHabits { reportHabits() }
    }

    /// The evening nudge names the habits not kept yet today.
    private func reportHabits() {
        NotificationManager.shared.setHabits(left: items.filter { checkedToday[$0.id] == nil }.map(\.text),
                                             total: items.count)
    }

    private func saveChecks() {
        guard restored, isHabits else { return }
        DiskCache.save(Checks(day: dayFormat.string(from: Date()), checked: checkedToday, streaks: streaks),
                       key: "habits.checks", userId: userId)
        reportHabits()
    }

    func load(api: APIClient) async {
        restore(api)
        loadTask?.cancel()
        let gen = beginLoad()
        let task = Task { @MainActor in
            defer { endLoad(gen) }
            // Unsent changes first; while any wait, what is on the phone is the newer copy.
            await Outbox.shared.drain(api)
            guard Outbox.shared.isEmpty else { offline = true; return }
            do {
                let rows = try await api.listItems(list, done: done)
                let checks = isHabits ? try await checkIns(api: api) : nil
                guard isCurrentLoad(gen) else { return }
                items = rows
                if let checks { (checkedToday, streaks) = checks }
                markLoaded()
                if !done { SpotlightIndexer.indexItems(list: list, rows) }
            } catch {
                failLoad(error, generation: gen) { notify("blocks.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// The same list's other half (open ↔ done), every copy of it.
    private func editOther(_ change: (inout [ListItem]) -> Void) {
        editCopies(Self.live.all.filter { $0.list == list && $0.done != done && $0.restored },
                   rows: \.items, key: Self.key(list, !done), userId: userId, change)
    }

    /// This half's other copies (another screen showing the same rows).
    private func editTwins(_ change: (inout [ListItem]) -> Void) {
        for twin in Self.live.all where twin !== self && twin.list == list && twin.done == done && twin.restored {
            change(&twin.items)
        }
    }

    func add(api: APIClient, text: String, due: Date? = nil, priority: String? = nil) async {
        restore(api)
        let row = ListItem(id: ClientID.make(), list: list, text: text, done: false,
                           due: due.map { isoOut.string(from: $0) }, priority: priority)
        let append: (inout [ListItem]) -> Void = { $0.append(row) }
        let remove: (inout [ListItem]) -> Void = { $0.removeAll { $0.id == row.id } }
        optimistic("blocks.errorSave",
                   apply: { append(&self.items); self.editTwins(append) },
                   rollback: { remove(&self.items); self.editTwins(remove) },
                   call: { try await api.addItem(id: row.id, list: self.list, text: text, due: due,
                                                 priority: priority) })
    }

    /// Today's check-ins (habit id → entry id) and each habit's run of days.
    private func checkIns(api: APIClient) async throws -> ([String: String], [String: Int]) {
        let cal = Calendar.current
        let today = dayFormat.string(from: Date())
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
            var day: Date? = set.contains(today) ? Date() : cal.date(byAdding: .day, value: -1, to: Date())
            var n = 0
            while let d = day, set.contains(dayFormat.string(from: d)) {
                n += 1
                day = cal.date(byAdding: .day, value: -1, to: d)
            }
            streaks[habit] = n
        }
        return (todays, streaks)
    }

    /// Ticks it done (or open again): it moves to the other half of the list.
    func toggle(api: APIClient, _ item: ListItem) {
        if isHabits { return checkIn(api: api, item) }
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        var moved = item
        moved.done.toggle()
        if moved.done { justDone = moved }
        let out: (inout [ListItem]) -> Void = { $0.removeAll { $0.id == item.id } }
        optimistic("blocks.errorSave",
                   apply: {
                       self.items.remove(at: idx)
                       self.editTwins(out)
                       self.editOther { $0.insert(moved, at: 0) }
                   },
                   rollback: {
                       self.items.insert(item, at: min(idx, self.items.count))
                       self.editTwins { $0.insert(item, at: min(idx, $0.count)) }
                       self.editOther { $0.removeAll { $0.id == item.id } }
                   },
                   call: { try await api.updateItem(id: item.id, done: moved.done) })
    }

    /// Puts the last ticked one back as open.
    func undoDone(api: APIClient) {
        guard let item = justDone else { return }
        justDone = nil
        var open = item
        open.done = false
        let back: (inout [ListItem]) -> Void = { rows in
            if !rows.contains(where: { $0.id == open.id }) { rows.insert(open, at: 0) }
        }
        optimistic("blocks.errorSave",
                   apply: {
                       back(&self.items)
                       self.editTwins(back)
                       self.editOther { $0.removeAll { $0.id == item.id } }
                   },
                   rollback: {
                       self.items.removeAll { $0.id == item.id }
                       self.editTwins { $0.removeAll { $0.id == item.id } }
                   },
                   call: { try await api.updateItem(id: item.id, done: false) })
    }

    /// Saves an edit in place; the row changes at once and comes back if the server refuses.
    func update(api: APIClient, _ item: ListItem, text: String, due: Date?, important: Bool) {
        guard let old = items.first(where: { $0.id == item.id }) else { return }
        var new = old
        new.text = text
        var change = APIClient.ItemChange()
        if text != old.text { change.text = text }
        if !isHabits {
            let priority = important ? "high" : "normal"
            new.priority = priority
            if priority != (old.priority ?? "normal") { change.priority = priority }
            if due != NotificationManager.parseISOOrDay(old.due ?? "") {
                change.due = .some(due)
                new.due = due.map { isoOut.string(from: $0) }
            }
        }
        let put: (ListItem) -> (inout [ListItem]) -> Void = { row in
            { rows in if let i = rows.firstIndex(where: { $0.id == row.id }) { rows[i] = row } }
        }
        optimistic("blocks.errorSave",
                   apply: { put(new)(&self.items); self.editTwins(put(new)) },
                   rollback: { put(old)(&self.items); self.editTwins(put(old)) },
                   call: { try await api.updateItem(id: item.id, change) })
    }

    func delete(api: APIClient, _ item: ListItem) {
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        let out: (inout [ListItem]) -> Void = { $0.removeAll { $0.id == item.id } }
        optimistic("blocks.errorSave",
                   apply: { self.items.remove(at: idx); self.editTwins(out) },
                   rollback: {
                       self.items.insert(item, at: min(idx, self.items.count))
                       self.editTwins { $0.insert(item, at: min(idx, $0.count)) }
                   },
                   call: { try await api.deleteItem(id: item.id) })
    }

    /// Check in today (a `habit` log entry), or undo today's check-in.
    private func checkIn(api: APIClient, _ item: ListItem) {
        let streak = streaks[item.id] ?? 0
        let habitStores = Self.live.all.filter { $0.isHabits && $0.restored }
        if let entryId = checkedToday[item.id] {
            optimistic("blocks.errorSave",
                       apply: {
                           for s in habitStores { s.checkedToday[item.id] = nil; s.streaks[item.id] = max(streak - 1, 0) }
                           LogStore.removeEverywhere(entryId, kind: "habit", userId: self.userId)
                       },
                       rollback: {
                           for s in habitStores { s.checkedToday[item.id] = entryId; s.streaks[item.id] = streak }
                       },
                       call: { try await api.deleteEntry(id: entryId) })
            return
        }
        let entry = LogEntry(id: ClientID.make(), kind: "habit", text: item.text,
                             at: isoOut.string(from: Date()),
                             data: ["habit_item_id": .string(item.id),
                                    "date": .string(dayFormat.string(from: Date()))])
        optimistic("blocks.errorSave",
                   apply: {
                       for s in habitStores { s.checkedToday[item.id] = entry.id; s.streaks[item.id] = streak + 1 }
                       LogStore.addEverywhere(entry, userId: self.userId)
                   },
                   rollback: {
                       for s in habitStores { s.checkedToday[item.id] = nil; s.streaks[item.id] = streak }
                       LogStore.removeEverywhere(entry.id, kind: "habit", userId: self.userId)
                   },
                   call: { try await api.addEntry(id: entry.id, kind: "habit", text: entry.text, data: entry.data) })
    }

    /// Tasks feed the home-screen widget and their due-time notifications.
    private func publishTasks() {
        let tasks = items.map { TaskItem(id: $0.id, text: $0.text, done: false,
                                         dueAt: $0.due ?? "", priority: $0.priority ?? "normal") }
        WidgetData.setOpenTasks(tasks)
        WidgetData.setActiveTasks(count: tasks.count)
        NotificationManager.shared.setOpenTasks(tasks.count)
        let title = AppLocale.isArabic ? "مهمة" : "Task"
        let notes = items.compactMap { item -> NotificationItem? in
            guard let date = NotificationManager.parseISO(item.due ?? ""), date > Date() else { return nil }
            return NotificationItem(id: item.id, title: title, body: item.text, date: date)
        }
        NotificationManager.shared.sync(prefix: "task.", items: notes)
    }
}

// MARK: - Reminders

/// Upcoming reminders; the phone rings them as local notifications.
@MainActor
final class SchedulesStore: LoadableStore {
    private static let live = LiveStores<SchedulesStore>()

    let kind: String
    @Published var items: [ScheduleItem] = [] { didSet { saveItems() } }
    private var userId: String?
    private var restored = false

    init(kind: String = "reminder") {
        self.kind = kind
        super.init()
        Self.live.add(self)
    }

    private var cacheKey: String { "schedules.\(kind)" }

    private func restore(_ api: APIClient) {
        guard !restored else { return }
        userId = api.currentUserId
        if let cached = DiskCache.load([ScheduleItem].self, key: cacheKey, userId: userId) {
            items = cached
            hasSnapshot = true
        }
        restored = true
    }

    private func saveItems() {
        guard restored else { return }
        DiskCache.save(items, key: cacheKey, userId: userId)
        publish()
    }

    func load(api: APIClient) async {
        restore(api)
        let gen = beginLoad()
        defer { endLoad(gen) }
        await Outbox.shared.drain(api)
        guard Outbox.shared.isEmpty else { offline = true; return }
        do {
            let rows = try await api.schedules(kind: kind)
            guard isCurrentLoad(gen) else { return }
            items = Self.byTime(rows)
            markLoaded()
            if kind == "reminder" { SpotlightIndexer.indexReminders(items) }
        } catch {
            failLoad(error, generation: gen) { notify("blocks.errorLoad") }
        }
    }

    private static func byTime(_ rows: [ScheduleItem]) -> [ScheduleItem] {
        rows.sorted {
            (NotificationManager.parseISO($0.fireAt) ?? .distantFuture)
                < (NotificationManager.parseISO($1.fireAt) ?? .distantFuture)
        }
    }

    /// Every copy of this kind's reminders, this one included.
    private func everywhere(_ change: @escaping (inout [ScheduleItem]) -> Void) {
        editCopies(Self.live.all.filter { $0.kind == kind && $0.restored }, rows: \.items,
                   key: cacheKey, userId: userId) { rows in
            change(&rows)
            rows = Self.byTime(rows)
        }
    }

    /// A banner button (later / done / delete) acted while no screen was asked:
    /// every copy of the reminders follows.
    static func bannerAction(id: String, movedTo: Date?, userId: String?) {
        editCopies(live.all.filter { $0.kind == "reminder" && $0.restored }, rows: \.items,
                   key: "schedules.reminder", userId: userId) { rows in
            if let at = movedTo, let i = rows.firstIndex(where: { $0.id == id }) {
                rows[i].fireAt = isoOut.string(from: at)
            } else if movedTo == nil {
                rows.removeAll { $0.id == id }
            }
            rows = byTime(rows)
        }
    }

    private static func rule(_ name: String?) -> String? {
        name.map { "FREQ=" + $0.uppercased() }
    }

    func add(api: APIClient, text: String, at: Date, recurrence: String?) async -> Bool {
        restore(api)
        let row = ScheduleItem(id: ClientID.make(), kind: kind, text: text, fireAt: isoOut.string(from: at),
                               recurrence: Self.rule(recurrence) ?? "", status: "pending")
        optimistic("blocks.errorSave",
                   apply: { self.everywhere { $0.append(row) } },
                   rollback: { self.everywhere { $0.removeAll { $0.id == row.id } } },
                   call: { try await api.addSchedule(id: row.id, kind: self.kind, text: text, at: at,
                                                     recurrence: recurrence) })
        return true
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
        optimistic("blocks.errorSave",
                   apply: { self.everywhere { $0.removeAll { $0.id == item.id } } },
                   rollback: { self.everywhere { rows in
                       if !rows.contains(where: { $0.id == item.id }) { rows.append(item) }
                   } },
                   call: call)
    }

    private func replace(_ row: ScheduleItem) {
        everywhere { rows in if let i = rows.firstIndex(where: { $0.id == row.id }) { rows[i] = row } }
    }

    /// Edit text, time or repeat; recurrence nil makes it ring once.
    func update(api: APIClient, _ item: ScheduleItem, text: String, at: Date, recurrence: String?) async -> Bool {
        let moved = NotificationManager.parseISO(item.fireAt).map { abs($0.timeIntervalSince(at)) >= 60 } ?? true
        var new = item
        new.text = text
        new.recurrence = Self.rule(recurrence) ?? ""
        if moved { new.fireAt = isoOut.string(from: at) }
        optimistic("blocks.errorSave",
                   apply: { self.replace(new) },
                   rollback: { self.replace(item) },
                   call: { try await api.updateSchedule(id: item.id, at: moved ? at : nil,
                                                        text: text == item.text ? nil : text,
                                                        recurrence: recurrence ?? "") })
        return true
    }

    /// Later: the same reminder, `minutes` from now.
    func snooze(api: APIClient, _ item: ScheduleItem, minutes: Int) {
        let at = Date().addingTimeInterval(TimeInterval(minutes * 60))
        var new = item
        new.fireAt = isoOut.string(from: at)
        optimistic("blocks.errorSave",
                   apply: { self.replace(new) },
                   rollback: { self.replace(item) },
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

// MARK: - The log

/// The log: everything that happened, newest first, optionally one kind.
@MainActor
final class LogStore: LoadableStore {
    private static let live = LiveStores<LogStore>()

    @Published var entries: [LogEntry] = [] { didSet { saveEntries() } }
    @Published var kind: String? {
        didSet { if kind != oldValue { restored = false } }
    }
    private var userId: String?
    private var restored = false

    init(kind: String? = nil) {
        self.kind = kind
        super.init()
        Self.live.add(self)
    }

    private static func key(_ kind: String?) -> String { "entries.\(kind ?? "all")" }

    private func restore(_ api: APIClient) {
        guard !restored else { return }
        userId = api.currentUserId
        restored = true
        entries = DiskCache.load([LogEntry].self, key: Self.key(kind), userId: userId) ?? []
        hasSnapshot = !entries.isEmpty
    }

    private func saveEntries() {
        guard restored else { return }
        DiskCache.save(entries, key: Self.key(kind), userId: userId)
    }

    func load(api: APIClient) async {
        restore(api)
        let gen = beginLoad()
        defer { endLoad(gen) }
        await Outbox.shared.drain(api)
        guard Outbox.shared.isEmpty else { offline = true; return }
        do {
            let rows = try await api.entries(kind: kind)
            guard isCurrentLoad(gen) else { return }
            entries = rows
            markLoaded()
            if kind == nil { SpotlightIndexer.indexEntries(entries) }
        } catch {
            failLoad(error, generation: gen) { notify("blocks.errorLoad") }
        }
    }

    /// Every copy an entry of `kind` belongs in: that kind's, and "all" (which leaves
    /// chat summaries out).
    private static func everywhere(kind: String, userId: String?,
                                   _ change: (inout [LogEntry]) -> Void) {
        for filter in [kind, nil] where filter != nil || kind != "summary" {
            editCopies(live.all.filter { $0.kind == filter && $0.restored }, rows: \.entries,
                       key: key(filter), userId: userId, change)
        }
    }

    static func addEverywhere(_ entry: LogEntry, userId: String?) {
        everywhere(kind: entry.kind, userId: userId) { rows in
            rows.insert(entry, at: 0)
            rows.sort {
                (NotificationManager.parseISO($0.at ?? "") ?? .distantPast)
                    > (NotificationManager.parseISO($1.at ?? "") ?? .distantPast)
            }
        }
    }

    static func removeEverywhere(_ id: String, kind: String, userId: String?) {
        everywhere(kind: kind, userId: userId) { $0.removeAll { $0.id == id } }
    }

    private static func replaceEverywhere(_ entry: LogEntry, userId: String?) {
        everywhere(kind: entry.kind, userId: userId) { rows in
            if let i = rows.firstIndex(where: { $0.id == entry.id }) { rows[i] = entry }
        }
    }

    func add(api: APIClient, kind: String, text: String, amount: Double?, at: Date? = nil) async -> Bool {
        restore(api)
        let entry = LogEntry(id: ClientID.make(), kind: kind, text: text,
                             at: isoOut.string(from: at ?? Date()),
                             data: amount.map { ["amount": .number($0)] })
        optimistic("blocks.errorSave",
                   apply: { Self.addEverywhere(entry, userId: self.userId) },
                   rollback: { Self.removeEverywhere(entry.id, kind: kind, userId: self.userId) },
                   call: { try await api.addEntry(id: entry.id, kind: kind, text: text, data: entry.data, at: at) })
        return true
    }

    /// Edit text, amount or time; the amount goes into a copy of the row's data.
    func update(api: APIClient, _ entry: LogEntry, text: String, amount: Double?, at: Date) {
        guard let old = entries.first(where: { $0.id == entry.id }) else { return }
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
        if moved { new.at = isoOut.string(from: at) }
        optimistic("blocks.errorSave",
                   apply: { Self.replaceEverywhere(new, userId: self.userId) },
                   rollback: { Self.replaceEverywhere(old, userId: self.userId) },
                   call: { try await api.updateEntry(id: entry.id, text: text == old.text ? nil : text,
                                                     data: data, at: moved ? at : nil) })
    }

    func delete(api: APIClient, _ entry: LogEntry) {
        optimistic("blocks.errorSave",
                   apply: { Self.removeEverywhere(entry.id, kind: entry.kind, userId: self.userId) },
                   rollback: { Self.addEverywhere(entry, userId: self.userId) },
                   call: { try await api.deleteEntry(id: entry.id) })
    }
}
