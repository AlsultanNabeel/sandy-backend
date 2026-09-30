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
    private var loadTask: Task<Void, Never>?

    init(list: String) { self.list = list }

    var isHabits: Bool { list == "habits" }

    private static let day: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    func load(api: APIClient) async {
        loadTask?.cancel()
        let gen = beginLoad()
        let task = Task { @MainActor in
            defer { endLoad(gen) }
            do {
                let rows = try await api.listItems(list, done: showDone)
                let today = isHabits ? try await todaysCheckIns(api: api) : [:]
                guard isCurrentLoad(gen) else { return }
                items = rows
                checkedToday = today
                markLoaded()
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

    func add(api: APIClient, text: String) async {
        do {
            try await api.addItem(list: list, text: text)
            clearNotice()
            await load(api: api)
        } catch {
            notify("blocks.errorSave")
        }
    }

    private func todaysCheckIns(api: APIClient) async throws -> [String: String] {
        let today = Self.day.string(from: Date())
        var out: [String: String] = [:]
        for e in try await api.entries(kind: "habit", limit: 100) {
            if case .string(let date)? = e.data?["date"], date == today,
               case .string(let habit)? = e.data?["habit_item_id"] {
                out[habit] = e.id
            }
        }
        return out
    }

    func toggle(api: APIClient, _ item: ListItem) {
        if isHabits { return checkIn(api: api, item) }
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        let removed = items[idx]
        // It leaves this filter (open ↔ done), so it leaves the list.
        optimistic("blocks.errorSave",
                   apply: { self.items.remove(at: idx) },
                   rollback: { self.items.insert(removed, at: min(idx, self.items.count)) },
                   call: { try await api.updateItem(id: item.id, done: !item.done) })
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
            optimistic("blocks.errorSave",
                       apply: { self.checkedToday[item.id] = nil },
                       rollback: { self.checkedToday[item.id] = entry },
                       call: { try await api.deleteEntry(id: entry) })
            return
        }
        checkedToday[item.id] = ""
        Task { @MainActor in
            do {
                try await api.addEntry(kind: "habit", text: item.text, data: [
                    "habit_item_id": .string(item.id),
                    "date": .string(Self.day.string(from: Date()))])
                checkedToday = try await todaysCheckIns(api: api)
            } catch {
                checkedToday[item.id] = nil
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
        do {
            let rows = try await api.schedules(kind: kind)
            guard isCurrentLoad(gen) else { return }
            items = rows.sorted { $0.fireAt < $1.fireAt }
            markLoaded()
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
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        let removed = items[idx]
        optimistic("blocks.errorSave",
                   apply: { self.items.remove(at: idx); self.publish() },
                   rollback: { self.items.insert(removed, at: min(idx, self.items.count)); self.publish() },
                   call: { try await api.deleteSchedule(id: item.id) })
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
        do {
            let rows = try await api.entries(kind: kind)
            guard isCurrentLoad(gen) else { return }
            entries = kind == nil ? rows.filter { $0.kind != "summary" } : rows
            markLoaded()
            if kind == nil { SpotlightIndexer.indexEntries(entries) }
        } catch {
            failLoad(error, generation: gen) { notify("blocks.errorLoad") }
        }
    }

    func add(api: APIClient, kind: String, text: String, amount: Double?) async -> Bool {
        do {
            try await api.addEntry(kind: kind, text: text,
                                   data: amount.map { ["amount": .number($0)] })
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("blocks.errorSave")
            return false
        }
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
