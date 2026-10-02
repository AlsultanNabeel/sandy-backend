import Foundation

extension APIClient {
    private struct Rows<T: Decodable>: Decodable { let items: [T]? }
    private struct Kinds: Decodable { let kinds: [BlockKind]? }
    private struct Summary: Decodable { let text: String? }

    fileprivate static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    /// Writes go through the outbox: sent now, or kept until the network is back.
    private func queued(_ path: String, method: String, body: (any Encodable)? = nil) async throws {
        try await Outbox.shared.send(self, path, method: method, body: body)
    }

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

    /// Newest first; `q` searches the text and `since`/`until` bound the time, over the whole log.
    func entries(kind: String? = nil, limit: Int = 200, q: String? = nil,
                 since: Date? = nil, until: Date? = nil) async throws -> [LogEntry] {
        let r: Rows<LogEntry> = try await fetch(query("/api/entries", [
            "kind": kind, "limit": String(limit), "q": q,
            "since": since.map { Self.iso.string(from: $0) },
            "until": until.map { Self.iso.string(from: $0) }]))
        return r.items ?? []
    }

    private struct Budget: Encodable { let amount: Double }

    /// The monthly spending limit; 0 removes it.
    func setBudget(_ amount: Double) async throws {
        try await queued("/api/budget", method: "POST", body: Budget(amount: amount))
    }

    /// My Life's numbers, counted on the server over the whole log.
    func stats() async throws -> LifeStats {
        try await fetch("/api/stats")
    }

    private struct EntryCreate: Encodable {
        let id: String
        let kind: String
        let text: String
        let data: [String: JSONValue]?
        let at: String?
    }

    func addEntry(id: String = ClientID.make(), kind: String, text: String,
                  data: [String: JSONValue]? = nil, at: Date? = nil) async throws {
        try await queued("/api/entries", method: "POST",
                         body: EntryCreate(id: id, kind: kind, text: text, data: data,
                                           at: at.map { Self.iso.string(from: $0) }))
    }

    /// Edit a log row: `data` replaces the row's data whole, so pass the merged copy.
    private struct EntryPatch: Encodable {
        let text: String?
        let data: [String: JSONValue]?
        let at: String?
    }

    func updateEntry(id: String, text: String? = nil, data: [String: JSONValue]? = nil,
                     at: Date? = nil) async throws {
        try await queued("/api/entries/\(id)", method: "PATCH",
                       body: EntryPatch(text: text, data: data, at: at.map { Self.iso.string(from: $0) }))
    }

    func deleteEntry(id: String) async throws {
        try await queued("/api/entries/\(id)", method: "DELETE")
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

    /// The project lists Sandy made from chat («project:<name>»), by name.
    func projectLists() async throws -> [String] {
        let r: Rows<ListItem> = try await fetch(query("/api/items", ["limit": "500"]))
        let names = (r.items ?? []).map(\.list).filter { $0.hasPrefix("project:") }
        return Array(Set(names)).sorted()
    }

    private struct ItemCreate: Encodable {
        let id: String
        let list: String
        let text: String
        let due: String?
        let priority: String?
        let data: [String: JSONValue]?
    }

    func addItem(id: String = ClientID.make(), list: String, text: String, due: Date? = nil,
                 priority: String? = nil, data: [String: JSONValue]? = nil) async throws {
        try await queued("/api/items", method: "POST",
                         body: ItemCreate(id: id, list: list, text: text,
                                          due: due.map { Self.iso.string(from: $0) }, priority: priority,
                                          data: data))
    }

    /// What an edit changes on a list item; nil leaves a field as it is.
    struct ItemChange: Encodable {
        var done: Bool?
        var text: String?
        var priority: String?
        /// The item's whole data (it replaces what is there).
        var data: [String: JSONValue]?
        /// nil keeps the time, `.some(nil)` clears it.
        var due: Date??

        func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: Key.self)
            try c.encodeIfPresent(done, forKey: .done)
            try c.encodeIfPresent(text, forKey: .text)
            try c.encodeIfPresent(priority, forKey: .priority)
            try c.encodeIfPresent(data, forKey: .data)
            if let due {
                if let date = due { try c.encode(APIClient.iso.string(from: date), forKey: .due) }
                else { try c.encodeNil(forKey: .due) }
            }
        }

        private enum Key: String, CodingKey { case done, text, priority, data, due }
    }

    func updateItem(id: String, _ change: ItemChange) async throws {
        try await queued("/api/items/\(id)", method: "PATCH", body: change)
    }

    func updateItem(id: String, done: Bool) async throws {
        try await updateItem(id: id, ItemChange(done: done))
    }

    func deleteItem(id: String) async throws {
        try await queued("/api/items/\(id)", method: "DELETE")
    }

    // MARK: schedules

    func schedules(kind: String? = nil) async throws -> [ScheduleItem] {
        let r: Rows<ScheduleItem> = try await fetch(query("/api/schedules",
                                                          ["kind": kind, "status": "pending"]))
        return r.items ?? []
    }

    private struct ScheduleCreate: Encodable {
        let id: String
        let kind: String
        let text: String
        let fire_at: String
        let recurrence: String?
    }

    /// recurrence: daily | weekly | monthly | yearly, or nil for once.
    func addSchedule(id: String = ClientID.make(), kind: String = "reminder", text: String, at: Date,
                     recurrence: String? = nil) async throws {
        try await queued("/api/schedules", method: "POST",
                         body: ScheduleCreate(id: id, kind: kind, text: text,
                                            fire_at: Self.iso.string(from: at),
                                            recurrence: recurrence))
    }

    private struct SchedulePatch: Encodable {
        let fire_at: String?
        let status: String?
        let text: String?
        let recurrence: String?
    }

    /// Edit, move (snooze) or close it; status is "pending" or "cancelled",
    /// recurrence "" makes it ring once.
    func updateSchedule(id: String, at: Date? = nil, status: String? = nil, text: String? = nil,
                        recurrence: String? = nil) async throws {
        try await queued("/api/schedules/\(id)", method: "PATCH",
                         body: SchedulePatch(fire_at: at.map { Self.iso.string(from: $0) }, status: status,
                                             text: text, recurrence: recurrence))
    }

    func deleteSchedule(id: String) async throws {
        try await queued("/api/schedules/\(id)", method: "DELETE")
    }
}
