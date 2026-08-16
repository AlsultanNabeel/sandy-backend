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

    // GET /api/life/shopping → {"items":[{id,text,done,category,price,qty,unit}], "demo":bool}
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

    // POST /api/life/shopping body {"text","category"} → {"ok":bool} (للمالك فقط)
    func addShopping(text: String, category: String = "") async throws {
        try await send("/api/life/shopping", method: "POST",
                       body: ShoppingCreate(text: text, category: category))
    }

    // Optional fields omit themselves from JSON when nil (encodeIfPresent), so a
    // nil price/qty is "not provided" exactly like the old dictionary build.
    private struct ShoppingCheck: Encodable {
        let price: Double?
        let qty: Int?
    }

    // PATCH /api/life/shopping/<id> body {"price"?,"qty"?} → {"ok":bool,...}
    // يشطب الغرض كـ"انشترى"؛ لو فيه سعر بيضيفه لمصاريفك تلقائياً.
    func checkShopping(id: String, price: Double? = nil, qty: Int? = nil) async throws {
        try await send("/api/life/shopping/\(id)", method: "PATCH",
                       body: ShoppingCheck(price: price, qty: qty))
    }

    // DELETE /api/life/shopping/<id> → {"ok":bool}
    func deleteShopping(id: String) async throws {
        try await send("/api/life/shopping/\(id)", method: "DELETE")
    }

    private struct ShoppingPrice: Encodable {
        let price: Double?
        let qty: Int?
        let unit: String?
    }

    // POST /api/life/shopping/<id>/price body {"price"?,"qty"?,"unit"?} → {"ok":bool}
    // يحدّد السعر/الكمية بدون ما يشطب — للإجمالي التقديري قبل الشراء.
    func setShoppingPrice(id: String, price: Double? = nil,
                          qty: Int? = nil, unit: String? = nil) async throws {
        guard price != nil || qty != nil || unit != nil else { return }
        try await send("/api/life/shopping/\(id)/price", method: "POST",
                       body: ShoppingPrice(price: price, qty: qty, unit: unit))
    }

    private struct LastPriceResponse: Decodable {
        let price: Double?
    }

    // GET /api/life/shopping/last-price?text= → {"price":number}
    // آخر سعر مدفوع لصنف بنفس الاسم. لا يرمي — يرجّع 0 عند أي فشل (اقتراح فقط).
    func shoppingLastPrice(text: String) async -> Double {
        let q = text.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        guard let r: LastPriceResponse = try? await fetch("/api/life/shopping/last-price?text=\(q)")
        else { return 0 }
        return r.price ?? 0
    }
}
