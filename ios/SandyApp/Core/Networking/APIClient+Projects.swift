import Foundation

extension APIClient {
    // MARK: - المشاريع (عصف ذهني)

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

    func getActiveBrainstorm() async throws -> ActiveBrainstorm? {
        makeActive(try await fetch("/api/plans/active"))
    }

    private struct TopicBody: Encodable {
        let topic: String
    }

    func startBrainstorm(topic: String) async throws -> ActiveBrainstorm? {
        makeActive(try await fetch("/api/plans/start", method: "POST", body: TopicBody(topic: topic)))
    }

    private struct PointBody: Encodable {
        let point: String
    }

    func addBrainstormPoint(_ point: String) async throws {
        try await send("/api/plans/active/points", method: "POST", body: PointBody(point: point))
    }

    /// Shared by finish (uses topic + plan_text) and update (plan_text only).
    private struct PlanTextResponse: Decodable {
        let plan_text: String?
        let topic: String?
    }

    func finishBrainstorm() async throws -> ProjectPlan {
        let r: PlanTextResponse = try await fetch("/api/plans/active/finish", method: "POST")
        return ProjectPlan(id: "", topic: r.topic ?? "",
                           summary: "", finishedAt: "",
                           planText: r.plan_text ?? "")
    }

    func cancelBrainstorm() async throws {
        try await send("/api/plans/active/cancel", method: "POST")
    }

    private struct ChangeBody: Encodable {
        let change: String
    }

    func updatePlan(id: String, change: String) async throws -> String {
        let r: PlanTextResponse = try await fetch("/api/plans/\(id)", method: "PATCH",
                                                  body: ChangeBody(change: change))
        return r.plan_text ?? ""
    }

    func deletePlan(id: String) async throws {
        try await send("/api/plans/\(id)", method: "DELETE")
    }

    /// صوت ساندي (WAV من جيميني) لنصّ معيّن؛ بايتات خام، فبيضل على URLSession مباشرة.
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
