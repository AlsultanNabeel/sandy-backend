import SwiftUI

extension APIClient {
    /// رد قائمة الأهداف. الحقول اختيارية لتحمّل غياب أي مفتاح بأمان (نفس تسامح
    /// الفكّ اليدوي القديم) — صف بلا id يُتجاهل.
    private struct GoalsResponse: Decodable {
        let items: [Row]
        struct Row: Decodable {
            let id: String?
            let text: String?
            let deadline: String?
            let status: String?
        }
    }

    // GET /api/goals → {"items":[{id,text,deadline,status}]}
    func getGoals() async throws -> [GoalItem] {
        let r: GoalsResponse = try await fetch("/api/goals")
        return r.items.compactMap { row in
            guard let id = row.id, !id.isEmpty else { return nil }
            return GoalItem(id: id,
                            text: row.text ?? "",
                            deadline: row.deadline ?? "",
                            status: row.status ?? "active")
        }
    }

    /// جسم إنشاء هدف. deadline اختياري: nil يُحذف من الـJSON (فالباك-إند يعتبره غير محدد).
    private struct GoalCreate: Encodable {
        let text: String
        let deadline: String?
    }

    // POST /api/goals {text, deadline?} → {"ok":true,"id"} — سجّل هدفاً جديداً.
    func addGoal(text: String, deadline: String = "") async throws {
        try await send("/api/goals", method: "POST",
                       body: GoalCreate(text: text, deadline: deadline.isEmpty ? nil : deadline))
    }

    /// جسم تعديل الهدف. كل الحقول اختيارية — nil يُحذف من الـJSON، فالحقل الغائب =
    /// بلا تغيير؛ وdeadline حاضر (حتى "") يمسح الموعد بالباك-إند.
    private struct GoalUpdate: Encodable {
        let text: String?
        let deadline: String?
        let status: String?
    }

    // PATCH /api/goals/<id> — تعديل: نص/موعد/حالة. الغائب = بلا تغيير.
    func updateGoal(id: String,
                    text: String? = nil,
                    deadline: String? = nil,
                    status: String? = nil) async throws {
        guard text != nil || deadline != nil || status != nil else { return }
        try await send("/api/goals/\(id)", method: "PATCH",
                       body: GoalUpdate(text: text, deadline: deadline, status: status))
    }

    // DELETE /api/goals/<id>
    func deleteGoal(id: String) async throws {
        try await send("/api/goals/\(id)", method: "DELETE")
    }
}
