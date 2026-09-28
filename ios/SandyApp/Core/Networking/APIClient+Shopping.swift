import SwiftUI

extension APIClient {
    private struct ShoppingResponse: Decodable {
        let items: [Row]?
        struct Row: Decodable {
            let id: String?
            let text: String?
            let done: Bool?
            let category: String?
            let price: Double?
            let qty: Int?
            let unit: String?
        }
    }

    func getShopping() async throws -> [ShoppingItem] {
        let r: ShoppingResponse = try await fetch("/api/life/shopping")
        return (r.items ?? []).compactMap { row in
            guard let id = row.id, !id.isEmpty else { return nil }
            return ShoppingItem(
                id: id,
                text: row.text ?? "",
                done: row.done ?? false,
                category: row.category ?? "",
                price: row.price ?? 0,
                qty: row.qty ?? 1,
                unit: row.unit ?? "")
        }
    }

    private struct ShoppingCreate: Encodable {
        let text: String
        let category: String
    }

    // (للمالك فقط)
    func addShopping(text: String, category: String = "") async throws {
        try await send("/api/life/shopping", method: "POST",
                       body: ShoppingCreate(text: text, category: category))
    }

    // nil fields are omitted from the JSON ("not provided").
    private struct ShoppingCheck: Encodable {
        let price: Double?
        let qty: Int?
    }

    // يشطب الغرض كـ"انشترى"؛ لو فيه سعر بيضيفه لمصاريفك تلقائياً.
    func checkShopping(id: String, price: Double? = nil, qty: Int? = nil) async throws {
        try await send("/api/life/shopping/\(id)", method: "PATCH",
                       body: ShoppingCheck(price: price, qty: qty))
    }

    func deleteShopping(id: String) async throws {
        try await send("/api/life/shopping/\(id)", method: "DELETE")
    }

    private struct LastPriceResponse: Decodable {
        let price: Double?
    }

    // آخر سعر لصنف بنفس الاسم؛ بيرجّع 0 عند أي فشل (اقتراح فقط).
    func shoppingLastPrice(text: String) async -> Double {
        let q = text.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        guard let r: LastPriceResponse = try? await fetch("/api/life/shopping/last-price?text=\(q)")
        else { return 0 }
        return r.price ?? 0
    }
}
