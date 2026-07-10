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

    /// Optional fields omit themselves from JSON when nil (encodeIfPresent), so a
    /// nil note/priority is "not provided" exactly like the old dictionary build.
    private struct TaskCreate: Encodable {
        let text: String
        let due: String
        let note: String?
        let priority: String?
    }

    // POST /api/tasks body {"text","due","note"?,"priority"?} → {"ok":true,"id":...}
    func addTask(text: String, due: String = "",
                 note: String? = nil, priority: String? = nil) async throws {
        try await send("/api/tasks", method: "POST",
                       body: TaskCreate(text: text, due: due, note: note, priority: priority))
    }

    private struct TaskDone: Encodable {
        let done: Bool
    }

    // PATCH /api/tasks/<id> body {"done":bool} (للمالك فقط)
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

    // PATCH /api/tasks/<id> — تعديل شامل: نص/إنجاز/ملاحظة/أولوية. الغائب = بلا تغيير.
    func updateTask(id: String, text: String? = nil, done: Bool? = nil,
                    note: String? = nil, priority: String? = nil, due: String? = nil) async throws {
        guard text != nil || done != nil || note != nil || priority != nil || due != nil else { return }
        try await send("/api/tasks/\(id)", method: "PATCH",
                       body: TaskUpdate(text: text, done: done, note: note, priority: priority, due: due))
    }

    // DELETE /api/tasks/<id> — deleteTask معرّف بقسم الخط الزمني.

    // ── التذكيرات ───────────────────────────────────────────────────────
    private struct RemindersResponse: Decodable {
        let items: [Row]?
        let demo: Bool?
        struct Row: Decodable {
            let id: String?
            let text: String?
            let remind_at: String?
            let is_recurring: Bool?
            let note: String?
        }
    }

    // GET /api/reminders → {"items":[{id,text,remind_at,is_recurring,note?}], "demo":bool}
    func getReminders() async throws -> ListResult<ReminderItem> {
        let r: RemindersResponse = try await fetch("/api/reminders")
        let parsed: [ReminderItem] = (r.items ?? []).compactMap { row in
            guard let id = row.id, !id.isEmpty else { return nil }
            return ReminderItem(id: id,
                                text: row.text ?? "",
                                remindAt: row.remind_at ?? "",
                                isRecurring: row.is_recurring ?? false,
                                note: row.note ?? "")
        }
        return ListResult(items: parsed, demo: r.demo ?? false)
    }

    private struct ReminderCreate: Encodable {
        let text: String
        let remind_at: String
        let note: String?
    }

    // POST /api/reminders body {"text","remind_at","note"?} → {"ok":true} (للمالك فقط)
    func addReminder(text: String, remindAt: String, note: String? = nil) async throws {
        try await send("/api/reminders", method: "POST",
                       body: ReminderCreate(text: text, remind_at: remindAt, note: note))
    }

    private struct ReminderUpdate: Encodable {
        let text: String?
        let remind_at: String?
        let note: String?
    }

    // PATCH /api/reminders/<id> — تعديل: نص/وقت/ملاحظة. الغائب = بلا تغيير.
    func updateReminder(id: String, text: String? = nil,
                        remindAt: String? = nil, note: String? = nil) async throws {
        guard text != nil || remindAt != nil || note != nil else { return }
        try await send("/api/reminders/\(id)", method: "PATCH",
                       body: ReminderUpdate(text: text, remind_at: remindAt, note: note))
    }

    // DELETE /api/reminders/<id> → {"ok":true} (للمالك فقط)
    func deleteReminder(id: String) async throws {
        try await send("/api/reminders/\(id)", method: "DELETE")
    }

    // ── العادات ─────────────────────────────────────────────────────────
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

    // GET /api/life/habits → {"items":[{id,name,streak,done_today}], "demo":bool}
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

    // POST /api/life/habits body {"name"} → {"ok":bool} (للمالك فقط)
    func addHabit(name: String) async throws {
        try await send("/api/life/habits", method: "POST", body: HabitName(name: name))
    }

    // PATCH /api/life/habits/<id> body {"name"} → {"ok":bool} — إعادة تسمية العادة.
    func renameHabit(id: String, name: String) async throws {
        try await send("/api/life/habits/\(id)", method: "PATCH", body: HabitName(name: name))
    }

    // DELETE /api/life/habits/<id> → {"ok":bool} — حذف العادة.
    func deleteHabit(id: String) async throws {
        try await send("/api/life/habits/\(id)", method: "DELETE")
    }

    // POST /api/life/habits/checkin body {"name"} → {"ok":bool} (للمالك فقط)
    func checkinHabit(name: String) async throws {
        try await send("/api/life/habits/checkin", method: "POST", body: HabitName(name: name))
    }

    private struct HabitId: Encodable {
        let id: String
    }

    // POST /api/life/habits/uncheckin body {"id"} → {"ok":bool} (للمالك فقط)
    func uncheckinHabit(id: String) async throws {
        try await send("/api/life/habits/uncheckin", method: "POST", body: HabitId(id: id))
    }

    // ── الفوكس (بومودورو) ───────────────────────────────────────────────
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

    // GET /api/life/focus → حالة الجلسة الحالية.
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

    // POST /api/life/focus/start (للمالك فقط)
    func startFocus(focusMin: Int, breakMin: Int, cycles: Int,
                    scene: String, endScene: String, label: String) async throws {
        try await send("/api/life/focus/start", method: "POST",
                       body: FocusStart(focus_min: focusMin, break_min: breakMin, cycles: cycles,
                                        scene: scene, end_scene: endScene, label: label))
    }

    private struct FocusStop: Encodable {
        let cancel: Bool
    }

    // POST /api/life/focus/stop body {"cancel":bool} (للمالك فقط)
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

    // GET /api/life/focus/history?limit=
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
