import Foundation

extension APIClient {
    // MARK: - المشاريع (عصف ذهني: جلسة نشطة + خطط منجزة)

    private struct PlansResponse: Decodable {
        let items: [Row]?
        struct Row: Decodable {
            let id: String?
            let topic: String?
            let summary: String?
            let finished_at: String?
            let plan_text: String?
        }
    }

    // GET /api/plans → {"items":[{id,topic,summary,finished_at,plan_text}]}
    func getPlans() async throws -> [ProjectPlan] {
        let r: PlansResponse = try await fetch("/api/plans")
        return (r.items ?? []).map {
            ProjectPlan(id: $0.id ?? "",
                        topic: $0.topic ?? "",
                        summary: $0.summary ?? "",
                        finishedAt: $0.finished_at ?? "",
                        planText: $0.plan_text ?? "")
        }
    }

    private struct ActiveResponse: Decodable {
        let active: Active?
        struct Active: Decodable {
            let topic: String?
            let points: [String]?
            let started_at: String?
        }
    }

    private func makeActive(_ r: ActiveResponse) -> ActiveBrainstorm? {
        guard let a = r.active else { return nil }
        return ActiveBrainstorm(topic: a.topic ?? "",
                                points: a.points ?? [],
                                startedAt: a.started_at ?? "")
    }

    // GET /api/plans/active → {"active": {topic,points,started_at} | null}
    func getActiveBrainstorm() async throws -> ActiveBrainstorm? {
        makeActive(try await fetch("/api/plans/active"))
    }

    private struct TopicBody: Encodable {
        let topic: String
    }

    // POST /api/plans/start {topic} → {"active": {...}}
    func startBrainstorm(topic: String) async throws -> ActiveBrainstorm? {
        makeActive(try await fetch("/api/plans/start", method: "POST", body: TopicBody(topic: topic)))
    }

    private struct PointBody: Encodable {
        let point: String
    }

    // POST /api/plans/active/points {point}
    func addBrainstormPoint(_ point: String) async throws {
        try await send("/api/plans/active/points", method: "POST", body: PointBody(point: point))
    }

    /// Shared by finish (uses topic + plan_text) and update (plan_text only).
    private struct PlanTextResponse: Decodable {
        let plan_text: String?
        let topic: String?
    }

    // POST /api/plans/active/finish → {"plan_text","topic"}
    func finishBrainstorm() async throws -> ProjectPlan {
        let r: PlanTextResponse = try await fetch("/api/plans/active/finish", method: "POST")
        return ProjectPlan(id: "", topic: r.topic ?? "",
                           summary: "", finishedAt: "",
                           planText: r.plan_text ?? "")
    }

    // POST /api/plans/active/cancel
    func cancelBrainstorm() async throws {
        try await send("/api/plans/active/cancel", method: "POST")
    }

    private struct ChangeBody: Encodable {
        let change: String
    }

    // PATCH /api/plans/<id> {change} → {"plan_text"}
    func updatePlan(id: String, change: String) async throws -> String {
        let r: PlanTextResponse = try await fetch("/api/plans/\(id)", method: "PATCH",
                                                  body: ChangeBody(change: change))
        return r.plan_text ?? ""
    }

    // DELETE /api/plans/<id>
    func deletePlan(id: String) async throws {
        try await send("/api/plans/\(id)", method: "DELETE")
    }

    // حذف عنصر من مصدره الأصلي (حسب نوعه) — حرية الحذف من الخط الزمني.
    func deleteTask(id: String) async throws {
        try await send("/api/tasks/\(id)", method: "DELETE")
    }

    func deleteExpense(id: String) async throws {
        try await send("/api/life/expenses/\(id)", method: "DELETE")
    }

    private struct ExpenseUpdate: Encodable {
        let amount: Double?
        let note: String?
        let category: String?
    }

    // PATCH /api/life/expenses/<id> — تعديل: مبلغ/ملاحظة/تصنيف. الغائب = بلا تغيير.
    func updateExpense(id: String, amount: Double? = nil,
                       note: String? = nil, category: String? = nil) async throws {
        guard amount != nil || note != nil || category != nil else { return }
        try await send("/api/life/expenses/\(id)", method: "PATCH",
                       body: ExpenseUpdate(amount: amount, note: note, category: category))
    }

    func deleteJournalEntry(id: String) async throws {
        try await send("/api/life/journal/\(id)", method: "DELETE")
    }

    private struct JournalText: Encodable {
        let text: String
    }

    // PATCH /api/life/journal/<id> body {"text"} — تعديل نص التدوينة (إلزامي).
    func updateJournalEntry(id: String, text: String) async throws {
        try await send("/api/life/journal/\(id)", method: "PATCH", body: JournalText(text: text))
    }

    /// يجيب صوت ساندي الطبيعي (WAV من جيميني) لنصّ معيّن — للتشغيل ومزامنة الفم.
    /// ناتجه بايتات صوت خام (مش JSON)، فيبقى على URLSession مباشرة بدل fetch/send.
    func synthesizeVoice(text: String, mood: String = "neutral") async throws -> Data {
        guard let url = URL(string: baseURL + "/api/voice/tts") else {
            throw APIError(message: "عنوان غير صالح")
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        req.httpBody = try JSONSerialization.data(withJSONObject: ["text": text, "mood": mood])
        let (data, resp) = try await APIClient.sendWithRetry(
            req, method: req.httpMethod ?? "GET")
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code >= 400 { throw APIError(message: "صوت غير متاح (\(code))") }
        return data
    }
}
