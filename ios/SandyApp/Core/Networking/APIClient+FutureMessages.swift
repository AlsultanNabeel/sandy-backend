import SwiftUI

extension APIClient {
    /// A row without an id is dropped.
    private struct FutureMessagesResponse: Decodable {
        let items: [Row]?
        struct Row: Decodable {
            let id: String?
            let text: String?
            let deliver_at: String?
        }
    }

    func futureMessagesList() async throws -> [FutureMessage] {
        let r: FutureMessagesResponse = try await fetch("/api/future-messages")
        return (r.items ?? []).compactMap { row in
            guard let id = row.id, !id.isEmpty else { return nil }
            return FutureMessage(id: id,
                                 text: row.text ?? "",
                                 deliverAt: row.deliver_at ?? "")
        }
    }

    private struct FutureMessageCreate: Encodable {
        let text: String
        let deliver_at: String
    }

    func futureMessagesCreate(text: String, deliverAt: String) async throws {
        try await send("/api/future-messages", method: "POST",
                       body: FutureMessageCreate(text: text, deliver_at: deliverAt))
    }

    func futureMessagesDelete(id: String) async throws {
        try await send("/api/future-messages/\(id)", method: "DELETE")
    }
}
