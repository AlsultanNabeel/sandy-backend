import Foundation

extension APIClient {
    private struct TasksResponse: Decodable {
        let items: [Row]?
        let demo: Bool?
        struct Row: Decodable {
            let id: String?
            let text: String?
            let done: Bool?
            let due_at: String?
            let note: String?
            let priority: String?
        }
    }

    func getTasks(completed: Bool = false) async throws -> ListResult<TaskItem> {
        let path = completed ? "/api/tasks?completed=1" : "/api/tasks"
        let r: TasksResponse = try await fetch(path)
        let parsed: [TaskItem] = (r.items ?? []).compactMap { row in
            guard let id = row.id, !id.isEmpty else { return nil }
            let p = row.priority ?? ""
            return TaskItem(id: id,
                            text: row.text ?? "",
                            done: row.done ?? false,
                            dueAt: row.due_at ?? "",
                            note: row.note ?? "",
                            priority: p.isEmpty ? "normal" : p)
        }
        return ListResult(items: parsed, demo: r.demo ?? false)
    }

    /// nil fields are omitted from the JSON ("not provided").
    private struct TaskCreate: Encodable {
        let text: String
        let due: String
        let note: String?
        let priority: String?
    }

    func addTask(text: String, due: String = "",
                 note: String? = nil, priority: String? = nil) async throws {
        try await send("/api/tasks", method: "POST",
                       body: TaskCreate(text: text, due: due, note: note, priority: priority))
    }

    private struct TaskDone: Encodable {
        let done: Bool
    }

    // (للمالك فقط)
    func setTaskDone(id: String, done: Bool) async throws {
        try await send("/api/tasks/\(id)", method: "PATCH", body: TaskDone(done: done))
    }

    private struct TaskUpdate: Encodable {
        let text: String?
        let done: Bool?
        let note: String?
        let priority: String?
        let due: String?
    }

    // الغائب = بلا تغيير.
    func updateTask(id: String, text: String? = nil, done: Bool? = nil,
                    note: String? = nil, priority: String? = nil, due: String? = nil) async throws {
        guard text != nil || done != nil || note != nil || priority != nil || due != nil else { return }
        try await send("/api/tasks/\(id)", method: "PATCH",
                       body: TaskUpdate(text: text, done: done, note: note, priority: priority, due: due))
    }

    // deleteTask معرّف بقسم الخط الزمني.

    // ── التذكيرات ──
    private struct RemindersResponse: Decodable {
        let items: [Row]?
        let demo: Bool?
        struct Row: Decodable {
            let id: String?
            let text: String?
            let remind_at: String?
            let is_recurring: Bool?
            let recurrence: String?
            let note: String?
        }
    }

    func getReminders() async throws -> ListResult<ReminderItem> {
        let r: RemindersResponse = try await fetch("/api/reminders")
        let parsed: [ReminderItem] = (r.items ?? []).compactMap { row in
            guard let id = row.id, !id.isEmpty else { return nil }
            return ReminderItem(id: id,
                                text: row.text ?? "",
                                remindAt: row.remind_at ?? "",
                                isRecurring: row.is_recurring ?? false,
                                recurrence: row.recurrence ?? "",
                                note: row.note ?? "")
        }
        return ListResult(items: parsed, demo: r.demo ?? false)
    }

    private struct ReminderCreate: Encodable {
        let text: String
        let remind_at: String
        let note: String?
    }

    // (للمالك فقط)
    func addReminder(text: String, remindAt: String, note: String? = nil) async throws {
        try await send("/api/reminders", method: "POST",
                       body: ReminderCreate(text: text, remind_at: remindAt, note: note))
    }

    private struct ReminderUpdate: Encodable {
        let text: String?
        let remind_at: String?
        let note: String?
    }

    // الغائب = بلا تغيير.
    func updateReminder(id: String, text: String? = nil,
                        remindAt: String? = nil, note: String? = nil) async throws {
        guard text != nil || remindAt != nil || note != nil else { return }
        try await send("/api/reminders/\(id)", method: "PATCH",
                       body: ReminderUpdate(text: text, remind_at: remindAt, note: note))
    }

    // (للمالك فقط)
    func deleteReminder(id: String) async throws {
        try await send("/api/reminders/\(id)", method: "DELETE")
    }

    private struct ReminderActionBody: Encodable {
        let action: String
        let minutes: Int?
    }

    private struct ReminderActionResponse: Decodable {
        let remind_at: String?
        let is_recurring: Bool?
    }

    /// الوقت الجاي (فاضي = خلص وما عاد يرنّ).
    struct ReminderOutcome {
        let remindAt: String
        let isRecurring: Bool
    }

    /// «بعدين» بيعيد تسليحه بلا ما يلمس التكرار؛ «تمّ» بيطوي هالمرّة بس (المتكرّر بيرجع بموعده الجاي).
    @discardableResult
    func actOnReminder(id: String, action: String, minutes: Int? = nil) async throws -> ReminderOutcome {
        let r: ReminderActionResponse = try await fetch(
            "/api/reminders/\(id)", method: "PATCH",
            body: ReminderActionBody(action: action, minutes: minutes))
        return ReminderOutcome(remindAt: r.remind_at ?? "",
                               isRecurring: r.is_recurring ?? false)
    }

    @discardableResult
    func snoozeReminder(id: String, minutes: Int) async throws -> ReminderOutcome {
        try await actOnReminder(id: id, action: "snooze", minutes: minutes)
    }

    @discardableResult
    func completeReminder(id: String) async throws -> ReminderOutcome {
        try await actOnReminder(id: id, action: "done")
    }

    // ── العادات ──
    private struct HabitsResponse: Decodable {
        let items: [Row]?
        let demo: Bool?
        struct Row: Decodable {
            let id: String?
            let name: String?
            let streak: Int?
            let done_today: Bool?
        }
    }

    func getHabits() async throws -> ListResult<HabitItem> {
        let r: HabitsResponse = try await fetch("/api/life/habits")
        let parsed: [HabitItem] = (r.items ?? []).compactMap { row in
            guard let id = row.id, !id.isEmpty else { return nil }
            return HabitItem(id: id,
                             name: row.name ?? "",
                             streak: row.streak ?? 0,
                             doneToday: row.done_today ?? false)
        }
        return ListResult(items: parsed, demo: r.demo ?? false)
    }

    private struct HabitName: Encodable {
        let name: String
    }

    // (للمالك فقط)
    func addHabit(name: String) async throws {
        try await send("/api/life/habits", method: "POST", body: HabitName(name: name))
    }

    func renameHabit(id: String, name: String) async throws {
        try await send("/api/life/habits/\(id)", method: "PATCH", body: HabitName(name: name))
    }

    func deleteHabit(id: String) async throws {
        try await send("/api/life/habits/\(id)", method: "DELETE")
    }

    // (للمالك فقط)
    func checkinHabit(name: String) async throws {
        try await send("/api/life/habits/checkin", method: "POST", body: HabitName(name: name))
    }

    private struct HabitId: Encodable {
        let id: String
    }

    // (للمالك فقط)
    func uncheckinHabit(id: String) async throws {
        try await send("/api/life/habits/uncheckin", method: "POST", body: HabitId(id: id))
    }

    // ── الفوكس (بومودورو) ──
    private struct FocusStatusResponse: Decodable {
        let active: Bool?
        let label: String?
        let scene: String?
        let phase: String?
        let cycle_idx: Int?
        let cycles: Int?
        let focus_min: Int?
        let break_min: Int?
        let remaining_sec: Int?
        let total_sec: Int?
        let demo: Bool?
    }

    func getFocusStatus() async throws -> FocusStatus {
        let r: FocusStatusResponse = try await fetch("/api/life/focus")
        return FocusStatus(
            active: r.active ?? false,
            label: r.label ?? "",
            scene: r.scene ?? "",
            phase: r.phase ?? "focus",
            cycleIdx: r.cycle_idx ?? 1,
            cycles: r.cycles ?? 1,
            focusMin: r.focus_min ?? 25,
            breakMin: r.break_min ?? 0,
            remainingSec: r.remaining_sec ?? 0,
            totalSec: r.total_sec ?? 0,
            demo: r.demo ?? false)
    }

    private struct FocusStart: Encodable {
        let focus_min: Int
        let break_min: Int
        let cycles: Int
        let scene: String
        let end_scene: String
        let label: String
    }

    // (للمالك فقط)
    func startFocus(focusMin: Int, breakMin: Int, cycles: Int,
                    scene: String, endScene: String, label: String) async throws {
        try await send("/api/life/focus/start", method: "POST",
                       body: FocusStart(focus_min: focusMin, break_min: breakMin, cycles: cycles,
                                        scene: scene, end_scene: endScene, label: label))
    }

    private struct FocusStop: Encodable {
        let cancel: Bool
    }

    // (للمالك فقط)
    func stopFocus(cancel: Bool) async throws {
        try await send("/api/life/focus/stop", method: "POST", body: FocusStop(cancel: cancel))
    }

    private struct FocusHistoryResponse: Decodable {
        let sessions: [Row]?
        struct Row: Decodable {
            let label: String?
            let minutes: Int?
            let completed: Bool?
            let started_at: String?
        }
    }

    func getFocusHistory(limit: Int = 30) async throws -> [FocusSession] {
        let r: FocusHistoryResponse = try await fetch("/api/life/focus/history?limit=\(limit)")
        return (r.sessions ?? []).map { row in
            FocusSession(label: row.label ?? "",
                         minutes: row.minutes ?? 0,
                         completed: row.completed ?? false,
                         startedAt: row.started_at ?? "")
        }
    }
}
