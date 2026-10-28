import Foundation

// The owner's pages (`api/owner_api.py`): every turn the server kept, and what it cost.
// Anyone else is answered 404.

/// A JSON value of any shape, kept as its compact text (a tool's arguments and result).
struct JSONText: Decodable, Equatable {
    let text: String

    private indirect enum Value: Decodable {
        case null, bool(Bool), number(Double), string(String), array([Value]), object([String: Value])

        init(from decoder: Decoder) throws {
            let c = try decoder.singleValueContainer()
            if c.decodeNil() { self = .null }
            else if let b = try? c.decode(Bool.self) { self = .bool(b) }
            else if let n = try? c.decode(Double.self) { self = .number(n) }
            else if let s = try? c.decode(String.self) { self = .string(s) }
            else if let a = try? c.decode([Value].self) { self = .array(a) }
            else { self = .object(try c.decode([String: Value].self)) }
        }

        var foundation: Any {
            switch self {
            case .null: return NSNull()
            case .bool(let b): return NSNumber(value: b)
            case .number(let n): return n == n.rounded() && abs(n) < 1e15 ? NSNumber(value: Int64(n)) : NSNumber(value: n)
            case .string(let s): return s
            case .array(let a): return a.map(\.foundation)
            case .object(let o): return o.mapValues(\.foundation)
            }
        }
    }

    init(from decoder: Decoder) throws {
        let value = try Value(from: decoder)
        if case .string(let s) = value { text = s; return }
        let data = try JSONSerialization.data(withJSONObject: value.foundation,
                                              options: [.sortedKeys, .withoutEscapingSlashes, .fragmentsAllowed])
        text = String(decoding: data, as: UTF8.self)
    }
}

struct TraceModelCall: Decodable, Hashable {
    let provider: String
    let model: String
    let tokensIn: Int
    let tokensOut: Int
    let tokensCached: Int
    let ms: Int

    enum CodingKeys: String, CodingKey {
        case provider, model, ms
        case tokensIn = "tokens_in", tokensOut = "tokens_out", tokensCached = "tokens_cached"
    }
}

struct TraceTool: Decodable, Hashable {
    let name: String
    let ok: Bool
    let ms: Int
    /// Only on one turn of the owner's own; never in the list.
    let args: String?
    let result: String?

    enum CodingKeys: String, CodingKey { case name, ok, ms, args, result }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        ok = (try? c.decode(Bool.self, forKey: .ok)) ?? false
        ms = (try? c.decode(Int.self, forKey: .ms)) ?? 0
        args = (try? c.decodeIfPresent(JSONText.self, forKey: .args))?.text
        result = (try? c.decodeIfPresent(JSONText.self, forKey: .result))?.text
    }
}

/// One turn: the list's rows carry no words; one turn opened carries them when it is the
/// owner's own.
struct Trace: Decodable, Identifiable, Hashable {
    let id: String
    let userId: String
    let at: String
    let source: String
    let routedBy: String
    let tools: [TraceTool]
    let modelCalls: [TraceModelCall]
    let tokensIn: Int
    let tokensOut: Int
    let costUsd: Double
    let msTotal: Int
    let error: String?
    let encrypted: Bool
    let request: String?
    let reply: String?

    enum CodingKeys: String, CodingKey {
        case id = "_id", userId = "user_id", at, source, routedBy = "routed_by", tools
        case modelCalls = "model_calls", tokensIn = "tokens_in", tokensOut = "tokens_out"
        case costUsd = "cost_usd", msTotal = "ms_total", error, encrypted, request, reply
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        userId = (try? c.decode(String.self, forKey: .userId)) ?? ""
        at = (try? c.decode(String.self, forKey: .at)) ?? ""
        source = (try? c.decode(String.self, forKey: .source)) ?? ""
        routedBy = (try? c.decode(String.self, forKey: .routedBy)) ?? ""
        tools = (try? c.decode([TraceTool].self, forKey: .tools)) ?? []
        modelCalls = (try? c.decode([TraceModelCall].self, forKey: .modelCalls)) ?? []
        tokensIn = (try? c.decode(Int.self, forKey: .tokensIn)) ?? 0
        tokensOut = (try? c.decode(Int.self, forKey: .tokensOut)) ?? 0
        costUsd = (try? c.decode(Double.self, forKey: .costUsd)) ?? 0
        msTotal = (try? c.decode(Int.self, forKey: .msTotal)) ?? 0
        error = try? c.decodeIfPresent(String.self, forKey: .error)
        encrypted = (try? c.decode(Bool.self, forKey: .encrypted)) ?? false
        request = try? c.decodeIfPresent(String.self, forKey: .request)
        reply = try? c.decodeIfPresent(String.self, forKey: .reply)
    }

    /// The server's ISO time (microseconds and all) as a date.
    var date: Date? {
        let plain = at.replacingOccurrences(of: #"\.\d+"#, with: "", options: .regularExpression)
        return ISO8601DateFormatter().date(from: plain)
    }
}

struct CostReport: Decodable {
    struct User: Decodable, Hashable {
        let userId: String
        let label: String
        let turns: Int
        let tokensIn: Int
        let tokensOut: Int
        let usd: Double

        enum CodingKeys: String, CodingKey {
            case userId = "user_id", label, turns, usd
            case tokensIn = "tokens_in", tokensOut = "tokens_out"
        }
    }

    struct Source: Decodable, Hashable {
        let source: String
        let turns: Int
        let usd: Double
    }

    let days: Int
    let totalUsd: Double
    let byUser: [User]
    let bySource: [Source]

    enum CodingKeys: String, CodingKey {
        case days, totalUsd = "total_usd", byUser = "by_user", bySource = "by_source"
    }
}

private struct TracesResponse: Decodable {
    let traces: [Trace]
}

extension APIClient {
    func ownerTraces(limit: Int = 50) async throws -> [Trace] {
        let r: TracesResponse = try await fetch("/api/owner/traces?limit=\(limit)")
        return r.traces
    }

    func ownerTrace(id: String) async throws -> Trace {
        try await fetch("/api/owner/traces/\(URLEscape.segment(id))")
    }

    func ownerCosts(days: Int = 30) async throws -> CostReport {
        try await fetch("/api/owner/costs?days=\(days)")
    }
}
