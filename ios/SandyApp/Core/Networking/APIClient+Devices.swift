import Foundation

private struct NodeListResponse: Decodable {
    let items: [Row]?
    let demo: Bool?

    struct Row: Decodable {
        let nodeId: String?
        let label: String?
        let capabilities: [String]?
        let outputs: [String]?
        let firmwareVersion: String?
        let online: Bool?
        let lastSeen: String?
        let pairedAt: String?
        let telemetry: [String: Any]?

        enum CodingKeys: String, CodingKey {
            case label, capabilities, outputs, online, telemetry
            case nodeId = "node_id"
            case firmwareVersion = "firmware_version"
            case lastSeen = "last_seen"
            case pairedAt = "paired_at"
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            nodeId = try c.decodeIfPresent(String.self, forKey: .nodeId)
            label = try c.decodeIfPresent(String.self, forKey: .label)
            capabilities = try c.decodeIfPresent([String].self, forKey: .capabilities)
            firmwareVersion = try c.decodeIfPresent(String.self, forKey: .firmwareVersion)
            online = try c.decodeIfPresent(Bool.self, forKey: .online)
            lastSeen = try c.decodeIfPresent(String.self, forKey: .lastSeen)
            pairedAt = try c.decodeIfPresent(String.self, forKey: .pairedAt)
            // الباك بيرسل outputs ككائنات {id, kind} مش نصوص: نرجّع فاضي بدل ما نرمي.
            outputs = (try? c.decode([String].self, forKey: .outputs)) ?? []
            // قاموس مختلط الأنواع بينفكّ يدويًا. غيابه مش خطأ: عقدة الغرفة ما بتبعث تليمتري.
            if let raw = try? c.decode([String: TelemetryValue].self, forKey: .telemetry) {
                telemetry = raw.mapValues { $0.any }
            } else {
                telemetry = nil
            }
        }
    }
}

/// رقم أو بوليان — وسيط لأن Swift ما بيفكّ قاموسًا مختلط الأنواع لحاله.
private enum TelemetryValue: Decodable {
    case int(Int), bool(Bool), string(String)

    var any: Any {
        switch self {
        case .int(let v):    return NSNumber(value: v)
        case .bool(let v):   return v
        case .string(let v): return v
        }
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        // البوليان أولًا: true بينفكّ كـ Int(1) لو جرّبنا الرقم قبله.
        if let b = try? c.decode(Bool.self)   { self = .bool(b);   return }
        if let i = try? c.decode(Int.self)    { self = .int(i);    return }
        if let s = try? c.decode(String.self) { self = .string(s); return }
        throw DecodingError.dataCorruptedError(in: c, debugDescription: "قيمة تليمتري غير مدعومة")
    }
}

private struct PairNodeResponse: Decodable {
    let nodeId: String?
    let already: Bool?
    let needsPresence: Bool?
    let sent: Bool?

    enum CodingKeys: String, CodingKey {
        case already, sent
        case nodeId = "node_id"
        case needsPresence = "needs_presence"
    }
}

private struct NodeIrLastResponse: Decodable {
    let code: String?
    let at: String?
}

extension APIClient {
    func getDevices() async throws -> ListResult<DeviceItem> {
        let r = try await request("/api/devices")
        let items = r["items"] as? [[String: Any]] ?? []
        let parsed: [DeviceItem] = items.compactMap { row in
            guard let name = row["name"] as? String, !name.isEmpty else { return nil }
            let transport = DeviceTransport.from(row["transport"] as? [String: Any] ?? [:])
            // نص أو رقم أو بوليان → نص؛ البوليان بيتحوّل on/off بدل 1/0.
            let state: String
            if let s = row["state"] as? String {
                state = s
            } else if let n = row["state"] as? NSNumber {
                if CFGetTypeID(n) == CFBooleanGetTypeID() {
                    state = n.boolValue ? "on" : "off"
                } else {
                    state = n.stringValue
                }
            } else {
                state = ""
            }
            return DeviceItem(name: name,
                              label: row["label"] as? String ?? name,
                              room: row["room"] as? String ?? "",
                              controlType: row["control_type"] as? String ?? "switch",
                              transport: transport,
                              meta: row["meta"] as? [String: Any] ?? [:],
                              state: state,
                              online: row["online"] as? Bool ?? false,
                              lastSeen: row["last_seen"] as? String ?? "")
        }
        return ListResult(items: parsed, demo: r["demo"] as? Bool ?? false)
    }

    // `name` معرّف ثابت مولّد من التسمية.
    @discardableResult
    func addDevice(name: String, label: String, controlType: String,
                   transport: DeviceTransport, room: String = "",
                   meta: [String: Any] = [:]) async throws -> String {
        var body: [String: Any] = [
            "name": name,
            "label": label,
            "control_type": controlType,
            "transport": transport.asDict,
        ]
        if !room.isEmpty { body["room"] = room }
        if !meta.isEmpty { body["meta"] = meta }
        let r = try await request("/api/devices", method: "POST", body: body)
        return r["name"] as? String ?? name
    }

    // بس الحقول غير nil حتى ما نمسح قيمة قائمة بالخطأ.
    func updateDevice(name: String, label: String? = nil, room: String? = nil,
                      controlType: String? = nil, transport: DeviceTransport? = nil,
                      meta: [String: Any]? = nil) async throws {
        var body: [String: Any] = [:]
        if let label { body["label"] = label }
        if let room { body["room"] = room }
        if let controlType { body["control_type"] = controlType }
        if let transport { body["transport"] = transport.asDict }
        if let meta { body["meta"] = meta }
        guard !body.isEmpty else { return }
        _ = try await request("/api/devices/\(enc(name))", method: "PATCH", body: body)
    }

    func deleteDevice(name: String) async throws {
        try await send("/api/devices/\(enc(name))", method: "DELETE")
    }

    // الأفعال: switch on|off؛ dimmer on|off|set؛ cover open|close|stop؛ media on|off|pause؛ enum set؛ ir send.
    func controlDevice(name: String, action: String, value: String? = nil) async throws {
        var body: [String: String] = ["action": action]
        if let value, !value.isEmpty { body["value"] = value }
        try await send("/api/devices/\(enc(name))/control", method: "POST", body: body)
    }

    // الخادم بيصغّر الصورة ع ٢٤٠×٢٤٠ وبيحوّلها لصيغة الشاشة: فكّ الصور بياكل رام اللوح.
    func sendDeviceImage(name: String, jpegData: Data) async throws {
        try await send("/api/devices/\(enc(name))/image", method: "POST",
                       body: ["image_base64": jpegData.base64EncodedString()])
    }

    // آخر إطار من البثّ البعيد؛ `nil` = ما في إطار بعد (مش خطأ).
    func liveFrame(nodeId: String) async throws -> Data? {
        let r = try await rawGet("/api/nodes/\(enc(nodeId))/snapshot/live", timeout: 8)
        guard r.count > 2, r[r.startIndex] == 0xFF,
              r[r.index(after: r.startIndex)] == 0xD8 else { return nil }
        return r
    }

    // يفضّي الحساب بس بيخلّيه (والروبوت يضل ملكه) — منفصل عن الحذف.
    func resetAccountData() async throws {
        struct Reply: Decodable { let ok: Bool? }
        let _: Reply = try await fetch("/api/account/reset", method: "POST",
                                       body: ["confirm": "RESET"])
    }

    // حذف نهائي — شرط إلزامي بمتجر أبل.
    func deleteAccount() async throws {
        struct Reply: Decodable { let ok: Bool? }
        let _: Reply = try await fetch("/api/account", method: "DELETE",
                                       body: ["confirm": "DELETE"])
    }

    // بيرجّع الصورة أو تذكرة منسأل عنها: اللوح ممكن ياخد +٢٠ ثانية، ومهلة طويلة
    // كانت بتوقّف خيط خادم (عنده ١٦ بس).
    func cameraSnapshot(nodeId: String) async throws -> Data {
        let data = try await rawPost("/api/nodes/\(enc(nodeId))/snapshot", timeout: 20)

        // JPEG بتبدأ بـ FF D8.
        if data.count > 2, data[data.startIndex] == 0xFF,
           data[data.index(after: data.startIndex)] == 0xD8 {
            return data
        }
        struct Ticket: Decodable { let req_id: String? }
        guard let req = (try? JSONDecoder().decode(Ticket.self, from: data))?.req_id else {
            throw APIError(message: "no_photo")
        }

        // ٤٠ ثانية بتغطّي أبطأ ردّ شفناه؛ السؤال رخيص (كل ثانية ونص).
        let deadline = Date().addingTimeInterval(40)
        while Date() < deadline {
            try await Task.sleep(nanoseconds: 1_500_000_000)
            let r = try await rawGet("/api/nodes/\(enc(nodeId))/snapshot/\(enc(req))")
            if r.count > 2, r[r.startIndex] == 0xFF,
               r[r.index(after: r.startIndex)] == 0xD8 {
                return r
            }
        }
        throw APIError(message: "no_photo")
    }

    // بترجع أول ما ينبعت الطلب؛ النتيجة الحقيقية بحقل `ssid` بالنبضة الجاية (اللوح بياخد لحد ٢٥ ث).
    @discardableResult
    func switchNodeWiFi(nodeId: String, ssid: String, password: String,
                        board: String = "brain") async throws -> Int {
        // أسماء الحقول مطابقة لرد الخادم حرفيًا (`window_s`).
        struct Body: Encodable { let ssid: String; let password: String; let board: String }
        struct Reply: Decodable { let ok: Bool?; let window_s: Int? }
        let r: Reply = try await fetch("/api/nodes/\(enc(nodeId))/wifi",
                                       method: "POST",
                                       body: Body(ssid: ssid, password: password,
                                                  board: board))
        return r.window_s ?? 35
    }

    // هلّق نحفظ اسم الزر (وكود إن توفّر).
    func irLearn(name: String, button: String, code: String = "") async throws {
        try await send("/api/devices/\(enc(name))/ir-learn", method: "POST",
                       body: ["button": button, "code": code])
    }

    // ── وحدات ساندي (الربط) ──
    func getNodes() async throws -> ListResult<NodeItem> {
        let r: NodeListResponse = try await fetch("/api/nodes")
        let parsed: [NodeItem] = (r.items ?? []).compactMap { row in
            guard let id = row.nodeId, !id.isEmpty else { return nil }
            return NodeItem(nodeId: id,
                            label: row.label ?? id,
                            capabilities: row.capabilities ?? [],
                            outputs: row.outputs ?? [],
                            firmwareVersion: row.firmwareVersion ?? "",
                            online: row.online ?? false,
                            lastSeen: row.lastSeen ?? "",
                            pairedAt: row.pairedAt ?? "",
                            telemetry: NodeTelemetry(row.telemetry))
        }
        return ListResult(items: parsed, demo: r.demo ?? false)
    }

    // POST /api/nodes/pair → {ok,node_id,already} لوحدة إلك، أو {needs_presence,...} (202) لوحدة حرّة.
    @discardableResult
    func pairNode(code: String, label: String? = nil) async throws -> PairResult {
        var body: [String: String] = ["code": code]
        if let label, !label.isEmpty { body["label"] = label }
        let r: PairNodeResponse = try await fetch("/api/nodes/pair", method: "POST", body: body)
        return PairResult(nodeId: r.nodeId ?? "",
                          already: r.already ?? false,
                          needsPresence: r.needsPresence ?? false,
                          sent: r.sent ?? true)
    }

    // الخطوة التانية: الرمز اللي ظهر ع الشاشة. أخطاؤها بـ `APIError.code`.
    @discardableResult
    func confirmPairNode(code: String, presence: String, label: String? = nil) async throws -> PairResult {
        var body: [String: String] = ["code": code, "presence": presence]
        if let label, !label.isEmpty { body["label"] = label }
        let r: PairNodeResponse = try await fetch("/api/nodes/pair/confirm", method: "POST", body: body)
        return PairResult(nodeId: r.nodeId ?? "", already: r.already ?? false)
    }

    func renameNode(nodeId: String, label: String) async throws {
        try await send("/api/nodes/\(enc(nodeId))", method: "PATCH",
                       body: ["label": label])
    }

    // `board_wiped`: لو اللوح مطفي وقت الفك، بيضل فيه اسم شبكتك وكلمة سرّها.
    @discardableResult
    func unpairNode(nodeId: String) async throws -> Bool {
        struct Reply: Decodable { let board_wiped: Bool? }
        let r: Reply = try await fetch("/api/nodes/\(enc(nodeId))", method: "DELETE")
        return r.board_wiped ?? false
    }

    // تضع الوحدة بوضع التعلّم (تلتقط الضغطة القادمة).
    func nodeIrLearnStart(nodeId: String) async throws {
        try await send("/api/nodes/\(enc(nodeId))/ir/learn", method: "POST", body: [String: String]())
    }

    func nodeIrLast(nodeId: String) async throws -> (code: String, at: String) {
        let r: NodeIrLastResponse = try await fetch("/api/nodes/\(enc(nodeId))/ir/last")
        return (r.code ?? "", r.at ?? "")
    }
}
