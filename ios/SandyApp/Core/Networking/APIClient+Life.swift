import Foundation

extension APIClient {
    private struct ExpensesResponse: Decodable {
        let items: [Row]?
        let summary: Summary?
        let demo: Bool?
        struct Row: Decodable {
            let id: String?
            let amount: Double?
            let note: String?
            let category: String?
            let at: String?
        }
        struct Summary: Decodable {
            let total: Double?
            let count: Int?
        }
    }

    func getExpenses() async throws -> ExpensesResult {
        let r: ExpensesResponse = try await fetch("/api/life/expenses")
        let parsed: [ExpenseItem] = (r.items ?? []).compactMap { row in
            guard let id = row.id, !id.isEmpty else { return nil }
            return ExpenseItem(id: id,
                               amount: row.amount ?? 0,
                               note: row.note ?? "",
                               category: row.category ?? "",
                               at: row.at ?? "")
        }
        let s = r.summary
        let summary = ExpensesSummary(total: s?.total ?? 0, count: s?.count ?? 0)
        return ExpensesResult(items: parsed, summary: summary, demo: r.demo ?? false)
    }

    private struct ExpenseCreate: Encodable {
        let amount: Double
        let note: String
        let category: String
    }

    // POST /api/life/expenses body {"amount","note","category"} → {"ok":bool} (للمالك فقط)
    func addExpense(amount: Double, note: String, category: String) async throws {
        try await send("/api/life/expenses", method: "POST",
                       body: ExpenseCreate(amount: amount, note: note, category: category))
    }

    // ── اليوميات ────────────────────────────────────────────────────────
    private struct JournalResponse: Decodable {
        let items: [Row]?
        let demo: Bool?
        struct Row: Decodable {
            let id: String?
            let date: String?
            let text: String?
        }
    }

    // GET /api/life/journal → {"items":[{id,date,text}], "demo":bool}
    func getJournal() async throws -> ListResult<JournalEntry> {
        let r: JournalResponse = try await fetch("/api/life/journal")
        let parsed: [JournalEntry] = (r.items ?? []).compactMap { row in
            guard let id = row.id, !id.isEmpty else { return nil }
            return JournalEntry(id: id,
                                date: row.date ?? "",
                                text: row.text ?? "")
        }
        return ListResult(items: parsed, demo: r.demo ?? false)
    }

    private struct JournalCreate: Encodable {
        let text: String
    }

    // POST /api/life/journal body {"text"} → {"ok":bool} (للمالك فقط)
    func addJournalEntry(text: String) async throws {
        try await send("/api/life/journal", method: "POST", body: JournalCreate(text: text))
    }

    // ── لقطة الشاشة الرئيسية ─────────────────────────────────────────────
    /// تجميع خفيف وذكي للشاشة الرئيسية: يجلب المهام + التذكيرات + المصاريف
    /// بالتوازي، ويتحمّل فشل كل قسم وحده (لا يرمي خطأ — يرجّع لقطة جزئية).
    /// مبني بالكامل من نداءات GET الموجودة، بدون أي نقطة نهاية جديدة.
    func getHomeSnapshot() async -> HomeSnapshot {
        // نجلب الثلاثة بالتوازي؛ كل واحد محاط بـ try? فلا يُسقط البقية.
        async let tasksRes = try? getTasks()
        async let remindersRes = try? getReminders()
        async let expensesRes = try? getExpenses()

        let tasks = await tasksRes
        let reminders = await remindersRes
        let expenses = await expensesRes

        var snap = HomeSnapshot()
        // hadError = فشل قسم واحد على الأقل (رجّع nil).
        snap.hadError = (tasks == nil) || (reminders == nil) || (expenses == nil)

        let now = Date()
        let cal = Calendar.current
        // مُحلِّل ISO متسامح: ISO8601 يتطلّب منطقة زمنية، لكن الباك-إند يرسل
        // أحيانًا بلا منطقة (مثل "2026-06-05T16:00:00")، فنرجع لـ DateFormatter.
        let isoFull = ISO8601DateFormatter()
        isoFull.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let isoPlain = ISO8601DateFormatter()
        isoPlain.formatOptions = [.withInternetDateTime]
        let plainNoTZ = DateFormatter()
        plainNoTZ.locale = Locale(identifier: "en_US_POSIX")
        plainNoTZ.timeZone = TimeZone.current
        plainNoTZ.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        let dateOnly = DateFormatter()
        dateOnly.locale = Locale(identifier: "en_US_POSIX")
        dateOnly.timeZone = TimeZone.current
        dateOnly.dateFormat = "yyyy-MM-dd"
        func parseISO(_ s: String) -> Date? {
            if s.isEmpty { return nil }
            return isoFull.date(from: s)
                ?? isoPlain.date(from: s)
                ?? plainNoTZ.date(from: s)
                ?? dateOnly.date(from: s)
        }

        // ── المهام ──
        if let tasks {
            if tasks.demo { snap.demo = true }
            let open = tasks.items.filter { !$0.done }
            snap.openTasks = open.count
            for t in open {
                guard let due = parseISO(t.dueAt) else { continue }
                if due < now {
                    snap.overdueTasks += 1
                } else if cal.isDateInToday(due) {
                    snap.todayTasks += 1
                }
            }
            // عيّنة حتى 3 نصوص للعرض (مفتوحة، نتجاهل الفاضي).
            snap.sampleTaskTexts = open
                .map { $0.text }
                .filter { !$0.isEmpty }
                .prefix(3)
                .map { $0 }
        }

        // ── التذكيرات ──
        if let reminders {
            if reminders.demo { snap.demo = true }
            // القادمة فقط (وقتها ≥ الآن)، مرتّبة بالأقرب، حتى 3.
            let upcoming = reminders.items
                .compactMap { r -> (ReminderItem, Date)? in
                    guard let at = parseISO(r.remindAt), at >= now else { return nil }
                    return (r, at)
                }
                .sorted { $0.1 < $1.1 }
                .map { $0.0 }
            snap.upcomingReminders = Array(upcoming.prefix(3))
            if let first = upcoming.first {
                snap.nextReminderText = first.text
                snap.nextReminderAt = first.remindAt
            }
        }

        // ── المصاريف ──
        if let expenses {
            if expenses.demo { snap.demo = true }
            // إجمالي المدى (الملخّص) ≈ مصاريف الأسبوع/الشهر حسب نطاق الـ GET.
            snap.weekExpenseTotal = expenses.summary.total
            // مجموع مصاريف اليوم من العناصر التي وقتها اليوم.
            var todaySum = 0.0
            for e in expenses.items {
                if let at = parseISO(e.at), cal.isDateInToday(at) {
                    todaySum += e.amount
                }
            }
            snap.todayExpenseTotal = todaySum
        }

        return snap
    }
}
