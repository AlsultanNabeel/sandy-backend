import SwiftUI

extension APIClient {
    /// صف بلا id يُتجاهل.
    private struct GoalsResponse: Decodable {
        let items: [Row]
        struct Row: Decodable {
            let id: String?
            let text: String?
            let deadline: String?
            let status: String?
        }
    }

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

    /// deadline nil يُحذف من الـJSON = غير محدد.
    private struct GoalCreate: Encodable {
        let text: String
        let deadline: String?
    }

    func addGoal(text: String, deadline: String = "") async throws {
        try await send("/api/goals", method: "POST",
                       body: GoalCreate(text: text, deadline: deadline.isEmpty ? nil : deadline))
    }

    /// nil يُحذف = بلا تغيير؛ deadline حاضر (حتى "") يمسح الموعد.
    private struct GoalUpdate: Encodable {
        let text: String?
        let deadline: String?
        let status: String?
    }

    func updateGoal(id: String,
                    text: String? = nil,
                    deadline: String? = nil,
                    status: String? = nil) async throws {
        guard text != nil || deadline != nil || status != nil else { return }
        try await send("/api/goals/\(id)", method: "PATCH",
                       body: GoalUpdate(text: text, deadline: deadline, status: status))
    }

    func deleteGoal(id: String) async throws {
        try await send("/api/goals/\(id)", method: "DELETE")
    }
}
