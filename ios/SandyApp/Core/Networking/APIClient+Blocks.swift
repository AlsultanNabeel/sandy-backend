import Foundation

extension APIClient {
    private struct Rows<T: Decodable>: Decodable { let items: [T]? }
    private struct Kinds: Decodable { let kinds: [BlockKind]? }
    private struct Summary: Decodable { let text: String? }

    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private func query(_ path: String, _ params: [String: String?]) -> String {
        var c = URLComponents()
        c.queryItems = params.compactMap { k, v in v.map { URLQueryItem(name: k, value: $0) } }
            .sorted { $0.name < $1.name }
        let q = c.percentEncodedQuery ?? ""
        return q.isEmpty ? path : path + "?" + q
    }

    // MARK: kinds

    func blockKinds() async throws -> [BlockKind] {
        let r: Kinds = try await fetch("/api/kinds")
        return r.kinds ?? []
    }

    // MARK: log

    func entries(kind: String? = nil, limit: Int = 200) async throws -> [LogEntry] {
        let r: Rows<LogEntry> = try await fetch(query("/api/entries",
                                                      ["kind": kind, "limit": String(limit)]))
        return r.items ?? []
    }

    private struct EntryCreate: Encodable {
        let kind: String
        let text: String
        let data: [String: JSONValue]?
    }

    func addEntry(kind: String, text: String, data: [String: JSONValue]? = nil) async throws {
        try await send("/api/entries", method: "POST",
                       body: EntryCreate(kind: kind, text: text, data: data))
    }

    func deleteEntry(id: String) async throws {
        try await send("/api/entries/\(id)", method: "DELETE")
    }

    private struct SummaryAsk: Encodable { let period: String }

    /// period: today | yesterday | week | month | year.
    func summary(period: String) async throws -> String {
        let r: Summary = try await fetch("/api/summary", method: "POST",
                                         body: SummaryAsk(period: period), timeout: 60)
        return r.text ?? ""
    }

    // MARK: lists

    func listItems(_ list: String, done: Bool? = nil) async throws -> [ListItem] {
        let r: Rows<ListItem> = try await fetch(query("/api/items", [
            "list": list, "done": done.map { $0 ? "true" : "false" }]))
        return r.items ?? []
    }

    private struct ItemCreate: Encodable {
        let list: String
        let text: String
        let due: String?
    }

    func addItem(list: String, text: String, due: Date? = nil) async throws {
        try await send("/api/items", method: "POST",
                       body: ItemCreate(list: list, text: text, due: due.map { Self.iso.string(from: $0) }))
    }

    private struct ItemPatch: Encodable {
        let done: Bool?
        let text: String?
    }

    func updateItem(id: String, done: Bool? = nil, text: String? = nil) async throws {
        try await send("/api/items/\(id)", method: "PATCH", body: ItemPatch(done: done, text: text))
    }

    func deleteItem(id: String) async throws {
        try await send("/api/items/\(id)", method: "DELETE")
    }

    // MARK: schedules

    func schedules(kind: String? = nil) async throws -> [ScheduleItem] {
        let r: Rows<ScheduleItem> = try await fetch(query("/api/schedules",
                                                          ["kind": kind, "status": "pending"]))
        return r.items ?? []
    }

    private struct ScheduleCreate: Encodable {
        let kind: String
        let text: String
        let fire_at: String
        let recurrence: String?
    }

    /// recurrence: daily | weekly | monthly | yearly, or nil for once.
    func addSchedule(kind: String = "reminder", text: String, at: Date,
                     recurrence: String? = nil) async throws {
        try await send("/api/schedules", method: "POST",
                       body: ScheduleCreate(kind: kind, text: text,
                                            fire_at: Self.iso.string(from: at),
                                            recurrence: recurrence))
    }

    private struct SchedulePatch: Encodable {
        let fire_at: String?
        let status: String?
    }

    private struct ScheduleSaved: Decodable { let item: ScheduleItem? }

    /// Move it (snooze) or close it; status is "pending" or "cancelled".
    @discardableResult
    func updateSchedule(id: String, at: Date? = nil, status: String? = nil) async throws -> ScheduleItem? {
        let r: ScheduleSaved = try await fetch(
            "/api/schedules/\(id)", method: "PATCH",
            body: SchedulePatch(fire_at: at.map { Self.iso.string(from: $0) }, status: status))
        return r.item
    }

    func deleteSchedule(id: String) async throws {
        try await send("/api/schedules/\(id)", method: "DELETE")
    }
}
