import Foundation

/// رد قائمة الوحدات: عناصر الوحدة + علم البيانات التجريبية.
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
            // الباك يرسل outputs كمصفوفة كائنات {id, kind}، مش نصوص. نتساهل فنرجّع
            // فاضي بدل ما نرمي — نفس سلوك (as? [String] ?? []) قبل التطبيع.
            outputs = (try? c.decode([String].self, forKey: .outputs)) ?? []
            // قاموس أرقام وبوليان مختلطين — Decodable ما بيهضمه مباشرة، فبنفكّه
            // يدويًا. غيابه مش خطأ: عقدة الغرفة ما بتبعث تليمتري أصلًا.
            if let raw = try? c.decode([String: TelemetryValue].self, forKey: .telemetry) {
                telemetry = raw.mapValues { $0.any }
            } else {
                telemetry = nil
            }
        }
    }
}

/// قيمة تليمتري وحدة — رقم أو بوليان. لازمنا وسيط لأن Swift ما بيفكّ
/// قاموسًا مختلط الأنواع لحاله.
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
        // البوليان أولًا: بلغة سويفت، true بينفكّ كـ Int(1) لو جرّبنا الرقم قبله.
        if let b = try? c.decode(Bool.self)   { self = .bool(b);   return }
        if let i = try? c.decode(Int.self)    { self = .int(i);    return }
        if let s = try? c.decode(String.self) { self = .string(s); return }
        throw DecodingError.dataCorruptedError(in: c, debugDescription: "قيمة تليمتري غير مدعومة")
    }
}

/// رد ربط وحدة: المعرّف + هل كانت مربوطة سابقاً.
private struct PairNodeResponse: Decodable {
    let nodeId: String?
    let already: Bool?

    enum CodingKeys: String, CodingKey {
        case already
        case nodeId = "node_id"
    }
}

/// رد آخر كود أشعة التقطته الوحدة.
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
            // الحالة قد ترجع نصًّا أو رقمًا (أو بوليان JSON) — نوحّدها لنص. نفحص
            // النص أولًا؛ البوليان والأرقام كلاهما يجسر لـ NSNumber، ونميّز البوليان
            // بنوع قيمته (Bool) حتى نحوّله on/off بدل 1/0.
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

    // POST /api/devices {name,label,control_type,transport,room?,meta?} → {ok,name} | {error,allowed?}
    // نولّد `name` معرّفًا ثابتًا من التسمية حتى يبقى مستقرًّا (الباك-إند يقبله كـ id).
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

    // PATCH /api/devices/<name> {label?,room?,control_type?,transport?,meta?} → {ok}
    // نمرّر فقط الحقول غير nil حتى لا نمسح قيمة قائمة بالخطأ.
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

    // DELETE /api/devices/<name> → {ok}
    func deleteDevice(name: String) async throws {
        try await send("/api/devices/\(enc(name))", method: "DELETE")
    }

    // POST /api/devices/<name>/control {action,value?} → {ok,sent,payload}
    // أفعال حسب النوع: switch on|off؛ dimmer on|off أو set+قيمة رقمية؛
    // cover open|close|stop؛ media on|off|pause؛ enum set+قيمة؛ ir send+اسم زر.
    func controlDevice(name: String, action: String, value: String? = nil) async throws {
        var body: [String: String] = ["action": action]
        if let value, !value.isEmpty { body["value"] = value }
        try await send("/api/devices/\(enc(name))/control", method: "POST", body: body)
    }

    // POST /api/devices/<name>/image {image_base64} → {ok,chunks,bytes}
    //
    // منفصل عن /control لأنه الصورة مش أمر: التحكّم بياخد نص قصير وبينشره،
    // وهاد بياخد صورة، بيصغّرها ع ٢٤٠×٢٤٠، بيحوّلها لصيغة بكسلات الشاشة
    // بالضبط، وبينشرها ع عشرين رسالة. كل هاد بيصير ع الخادم — اللوح ما بيفك
    // ولا صيغة، لأن فاكّ الصور بياكل رام داخلية هي اللي بتخلّيها تحكي.
    func sendDeviceImage(name: String, jpegData: Data) async throws {
        try await send("/api/devices/\(enc(name))/image", method: "POST",
                       body: ["image_base64": jpegData.base64EncodedString()])
    }

    // DELETE /api/account — حذف نهائي. شرط إلزامي بمتجر أبل، ومطلوب أخلاقيًا:
    // الحساب فيه بصمة صوت ويوميات وصور ومصاريف.
    // POST /api/account/reset — يفضّي الحساب وبيخلّيه.
    //
    // منفصل عن الحذف لأنّ «بدّي أبدأ من جديد» و«بدّي أمشي» مش نفس الطلب:
    // اللي بدّه يبدأ من جديد بدّه يضلّ يملك **روبوته**. لو خلّيناه يحذف حسابه
    // عشان يمسح محادثة، بيخسر الجهاز معها.
    // GET /api/nodes/<id>/snapshot/live → آخر إطار من البثّ البعيد.
    //
    // نفس نقطة سحب الصورة العادية — الكاميرا بترفع الإطار بمعرّف ثابت `live`،
    // فالجديد بيستبدل القديم. بترجّع `nil` لو ما في إطار جاهز بعد، وهاد فرق
    // مهم عن الخطأ: بثّ لسا ما بلّش مش بثّ خربان.
    func liveFrame(nodeId: String) async throws -> Data? {
        let r = try await rawGet("/api/nodes/\(enc(nodeId))/snapshot/live", timeout: 8)
        guard r.count > 2, r[r.startIndex] == 0xFF,
              r[r.index(after: r.startIndex)] == 0xD8 else { return nil }
        return r
    }

    func resetAccountData() async throws {
        struct Reply: Decodable { let ok: Bool? }
        let _: Reply = try await fetch("/api/account/reset", method: "POST",
                                       body: ["confirm": "RESET"])
    }

    func deleteAccount() async throws {
        struct Reply: Decodable { let ok: Bool? }
        let _: Reply = try await fetch("/api/account", method: "DELETE",
                                       body: ["confirm": "DELETE"])
    }

    // POST /api/nodes/<id>/snapshot → إمّا الصورة، أو تذكرة نرجع فيها.
    //
    // **اللوح ما إله سرعة ثابتة.** بيردّ بثانية وهو فاضي، وبأكتر من عشرين وهو
    // مشغول. وكل نسخة سابقة حاولت تخبّي هالفرق جوّا نداء واحد: تحطّ مهلة، فإمّا
    // تكون قصيرة فترمي صورة وصلت سليمة، أو طويلة فتوقّف خيط خادم نص دقيقة —
    // والخادم عنده ستّة عشر خيط بس، يعني تلات ناس بيصوّروا سوا بيوقّفوا التطبيق
    // كلّه.
    //
    // فالخادم بيرجّع تذكرة، والصورة بتنحفظ عنده لمّا توصل، وإحنا منسأل عنها.
    // اللوح بياخد وقته، وما في مهلة لازم يلحقها حدا.
    func cameraSnapshot(nodeId: String) async throws -> Data {
        let data = try await rawPost("/api/nodes/\(enc(nodeId))/snapshot", timeout: 20)

        // الرد صورة؟ خلصنا. JPEG بتبدأ بـ FF D8.
        if data.count > 2, data[data.startIndex] == 0xFF,
           data[data.index(after: data.startIndex)] == 0xD8 {
            return data
        }
        struct Ticket: Decodable { let req_id: String? }
        guard let req = (try? JSONDecoder().decode(Ticket.self, from: data))?.req_id else {
            throw APIError(message: "no_photo")
        }

        // نسأل عنها. أربعين ثانية بتغطّي أبطأ ردّ شفناه بفرق كبير، والسؤال
        // نفسه رخيص — نداء صغير كل ثانية ونصف، مش خيط واقف مستنّي.
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

    // POST /api/nodes/<node_id>/wifi {ssid,password} → {ok, window_s}
    //
    // بترجع أول ما ينبعت الطلب، مش لما تنجح الشبكة. اللوح بده لحدّ خمسة وعشرين
    // ثانية يجرّب ويرجع للقديمة لو فشلت، والنتيجة الحقيقية بتوصل بنبضته الجاية
    // بحقل `ssid`.
    @discardableResult
    func switchNodeWiFi(nodeId: String, ssid: String, password: String,
                        board: String = "brain") async throws -> Int {
        // أسماء الحقول مطابقة لرد الخادم حرفيًا (`window_s`)، عشان ما يصير
        // مكانان بيسمّوا نفس الإشي وبيفترقوا.
        struct Body: Encodable { let ssid: String; let password: String; let board: String }
        struct Reply: Decodable { let ok: Bool?; let window_s: Int? }
        let r: Reply = try await fetch("/api/nodes/\(enc(nodeId))/wifi",
                                       method: "POST",
                                       body: Body(ssid: ssid, password: password,
                                                  board: board))
        return r.window_s ?? 35
    }

    // POST /api/devices/<name>/ir-learn {button,code} → {ok}
    // التقاط الكود الحقيقي يجي مع تحديث الوحدة لاحقًا — هلّق نحفظ اسم الزر (وكود إن توفّر).
    func irLearn(name: String, button: String, code: String = "") async throws {
        try await send("/api/devices/\(enc(name))/ir-learn", method: "POST",
                       body: ["button": button, "code": code])
    }

    // ── التحكّم بالبيت: وحدات ساندي (الربط) ──────────────────────────────────
    // GET /api/nodes → {"items":[{node_id,label,capabilities,outputs,
    //                            firmware_version,online,last_seen,paired_at}], "demo":bool}
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

    // POST /api/nodes/pair {code,label?} → {ok,node_id,already}
    @discardableResult
    func pairNode(code: String, label: String? = nil) async throws -> PairResult {
        var body: [String: String] = ["code": code]
        if let label, !label.isEmpty { body["label"] = label }
        let r: PairNodeResponse = try await fetch("/api/nodes/pair", method: "POST", body: body)
        return PairResult(nodeId: r.nodeId ?? "",
                          already: r.already ?? false)
    }

    // PATCH /api/nodes/<node_id> {label} → {ok}
    func renameNode(nodeId: String, label: String) async throws {
        try await send("/api/nodes/\(enc(nodeId))", method: "PATCH",
                       body: ["label": label])
    }

    // DELETE /api/nodes/<node_id> → {ok, board_wiped}
    //
    // بترجّع هل اللوح **انمسح** فعلًا، مش بس هل انفكّ الربط. التنين مش نفس
    // الإشي: لو كان مطفي وقت الطلب، الملكية بتتحرّر بس اسم شبكتك وكلمة سرّها
    // بيضلّوا محفوظين جوّاه — وبينباع فيهن.
    @discardableResult
    func unpairNode(nodeId: String) async throws -> Bool {
        struct Reply: Decodable { let board_wiped: Bool? }
        let r: Reply = try await fetch("/api/nodes/\(enc(nodeId))", method: "DELETE")
        return r.board_wiped ?? false
    }

    // POST /api/nodes/<node_id>/ir/learn → تضع الوحدة بوضع التعلّم (تلتقط الضغطة القادمة)
    func nodeIrLearnStart(nodeId: String) async throws {
        try await send("/api/nodes/\(enc(nodeId))/ir/learn", method: "POST", body: [String: String]())
    }

    // GET /api/nodes/<node_id>/ir/last → {code, at} — آخر كود أشعة التقطته الوحدة
    func nodeIrLast(nodeId: String) async throws -> (code: String, at: String) {
        let r: NodeIrLastResponse = try await fetch("/api/nodes/\(enc(nodeId))/ir/last")
        return (r.code ?? "", r.at ?? "")
    }
}
