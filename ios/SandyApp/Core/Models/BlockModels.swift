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

enum BlockType: String, Decodable {
    case log, list, schedule
}

struct BlockKind: Decodable, Identifiable, Hashable {
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

struct LogEntry: Codable, Identifiable, Hashable {
    let id: String
    let kind: String
    var text: String
    let at: String?
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
