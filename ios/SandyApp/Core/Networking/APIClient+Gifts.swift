import SwiftUI

extension APIClient {
    private struct GiftsResponse: Decodable {
        let items: [Row]?
        struct Row: Decodable {
            let id: String?
            let kind: String?
            let recipient: String?
            let occasion: String?
            let content: String?
            let scheduled_at: String?
        }
    }

    // GET /api/gifts → {"items":[{id,kind,recipient,occasion,content,scheduled_at}]}
    func getGifts() async throws -> [DigitalGift] {
        let r: GiftsResponse = try await fetch("/api/gifts")
        return (r.items ?? []).compactMap { row in
            guard let id = row.id, !id.isEmpty else { return nil }
            let kind = GiftKind(rawValue: row.kind ?? "smile") ?? .smile
            return DigitalGift(id: id,
                               kind: kind,
                               recipient: row.recipient ?? "",
                               occasion: row.occasion ?? "",
                               content: row.content ?? "",
                               scheduledAt: row.scheduled_at ?? "")
        }
    }

    private struct GiftCreate: Encodable {
        let kind: String
        let recipient: String
        let occasion: String
        let content: String
        let scheduled_at: String
    }

    // POST /api/gifts {kind,recipient,occasion,content,scheduled_at} → {"ok","id"}
    func addGift(kind: String, recipient: String, occasion: String,
                 content: String, scheduledAt: String) async throws {
        try await send("/api/gifts", method: "POST",
                       body: GiftCreate(kind: kind, recipient: recipient, occasion: occasion,
                                        content: content, scheduled_at: scheduledAt))
    }

    private struct GiftGenerate: Encodable {
        let kind: String
        let recipient: String
        let occasion: String
    }

    private struct GiftContentResponse: Decodable {
        let content: String?
    }

    // POST /api/gifts/generate {kind,recipient,occasion} → {"content"} — توليد نص (بلا حفظ).
    func giftsGenerate(kind: String, recipient: String, occasion: String) async throws -> String {
        let r: GiftContentResponse = try await fetch(
            "/api/gifts/generate", method: "POST",
            body: GiftGenerate(kind: kind, recipient: recipient, occasion: occasion))
        return r.content ?? ""
    }

    // DELETE /api/gifts/<id>
    func deleteGift(id: String) async throws {
        try await send("/api/gifts/\(id)", method: "DELETE")
    }
}
