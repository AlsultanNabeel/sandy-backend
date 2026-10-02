import Foundation

// The three blocks the server keeps (/api/entries, /api/items, /api/schedules) and
// the kinds table that describes them (/api/kinds). Every screen is built from these.

/// Any JSON value: a row's `data` differs per kind.
enum JSONValue: Codable, Hashable {
    case string(String), number(Double), bool(Bool), array([JSONValue])
    case object([String: JSONValue]), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        case .null: try c.encodeNil()
        }
    }

    var number: Double? { if case .number(let n) = self { return n }; return nil }
}

enum BlockType: String, Codable {
    case log, list, schedule
}

struct BlockKind: Codable, Identifiable, Hashable {
    let name: String
    let block: BlockType
    let labels: [String: String]
    let icon: String
    let prefix: Bool?

    var id: String { block.rawValue + ":" + name }

    func label(_ lang: AppLang) -> String {
        labels[lang.rawValue] ?? labels["ar"] ?? name
    }
}

/// My Life's numbers: entries on each of the last 30 days (oldest first) and this month's totals.
struct LifeStats: Codable, Hashable {
    var days: [Int]
    var spent: Double
    var habits: Int
    var logged: Int

    /// With entries made on the phone since the numbers were counted.
    func including(_ added: [LogEntry]) -> LifeStats {
        var out = self
        let cal = Calendar.current
        let today = cal.startOfDay(for: Date())
        for e in added {
            guard let at = NotificationManager.parseISO(e.at ?? "") else { continue }
            let back = cal.dateComponents([.day], from: cal.startOfDay(for: at), to: today).day ?? -1
            if back >= 0 && back < out.days.count { out.days[out.days.count - 1 - back] += 1 }
            guard cal.isDate(at, equalTo: Date(), toGranularity: .month) else { continue }
            out.logged += 1
            if e.kind == "habit" { out.habits += 1 }
            if e.kind == "expense" { out.spent += e.amount ?? 0 }
        }
        return out
    }
}

struct LogEntry: Codable, Identifiable, Hashable {
    let id: String
    let kind: String
    var text: String
    var at: String?
    var data: [String: JSONValue]?

    var amount: Double? { data?["amount"]?.number }
}

struct ListItem: Codable, Identifiable, Hashable {
    let id: String
    let list: String
    var text: String
    var done: Bool
    var due: String?
    var priority: String?
    var data: [String: JSONValue]?

    /// Tasks: daily | weekly | monthly, or nil for once.
    var repeatRule: String? {
        if case .string(let r)? = data?["repeat"], !r.isEmpty { return r }
        return nil
    }

    /// Habits: the weekdays it is kept on (1 = Sunday … 7 = Saturday); empty = every day.
    var habitDays: [Int] {
        guard case .array(let days)? = data?["days"] else { return [] }
        return days.compactMap { $0.number.map(Int.init) }
    }

    /// Habits: "HH:MM", when the phone reminds of it.
    var habitTime: String? {
        if case .string(let t)? = data?["time"], !t.isEmpty { return t }
        return nil
    }

    func isScheduled(on date: Date) -> Bool {
        habitDays.isEmpty || habitDays.contains(Calendar.current.component(.weekday, from: date))
    }
}

/// What the edit sheet hands back for a list item.
struct ItemDraft {
    var text: String
    var due: Date?
    var important: Bool
    var repeatRule: String?
    var days: [Int] = []
    var time: String?
}

struct ScheduleItem: Codable, Identifiable, Hashable {
    let id: String
    let kind: String
    var text: String
    var fireAt: String
    var recurrence: String?
    var status: String?

    enum CodingKeys: String, CodingKey {
        case id, kind, text, recurrence, status
        case fireAt = "fire_at"
    }
}
