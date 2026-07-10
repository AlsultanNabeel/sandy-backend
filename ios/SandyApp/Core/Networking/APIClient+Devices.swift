import Foundation

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
        _ = try await request("/api/devices/\(enc(name))", method: "DELETE")
    }

    // POST /api/devices/<name>/control {action,value?} → {ok,sent,payload}
    // أفعال حسب النوع: switch on|off؛ dimmer on|off أو set+قيمة رقمية؛
    // cover open|close|stop؛ media on|off|pause؛ enum set+قيمة؛ ir send+اسم زر.
    func controlDevice(name: String, action: String, value: String? = nil) async throws {
        var body: [String: Any] = ["action": action]
        if let value, !value.isEmpty { body["value"] = value }
        _ = try await request("/api/devices/\(enc(name))/control", method: "POST", body: body)
    }

    // POST /api/devices/<name>/ir-learn {button,code} → {ok}
    // التقاط الكود الحقيقي يجي مع تحديث الوحدة لاحقًا — هلّق نحفظ اسم الزر (وكود إن توفّر).
    func irLearn(name: String, button: String, code: String = "") async throws {
        _ = try await request("/api/devices/\(enc(name))/ir-learn", method: "POST",
                              body: ["button": button, "code": code])
    }

    // ── التحكّم بالبيت: وحدات ساندي (الربط) ──────────────────────────────────
    // GET /api/nodes → {"items":[{node_id,label,capabilities,outputs,
    //                            firmware_version,online,last_seen,paired_at}], "demo":bool}
    func getNodes() async throws -> ListResult<NodeItem> {
        let r = try await request("/api/nodes")
        let items = r["items"] as? [[String: Any]] ?? []
        let parsed: [NodeItem] = items.compactMap { row in
            guard let id = row["node_id"] as? String, !id.isEmpty else { return nil }
            return NodeItem(nodeId: id,
                            label: row["label"] as? String ?? id,
                            capabilities: row["capabilities"] as? [String] ?? [],
                            outputs: row["outputs"] as? [String] ?? [],
                            firmwareVersion: row["firmware_version"] as? String ?? "",
                            online: row["online"] as? Bool ?? false,
                            lastSeen: row["last_seen"] as? String ?? "",
                            pairedAt: row["paired_at"] as? String ?? "")
        }
        return ListResult(items: parsed, demo: r["demo"] as? Bool ?? false)
    }

    // POST /api/nodes/pair {code,label?} → {ok,node_id,already}
    @discardableResult
    func pairNode(code: String, label: String? = nil) async throws -> PairResult {
        var body: [String: Any] = ["code": code]
        if let label, !label.isEmpty { body["label"] = label }
        let r = try await request("/api/nodes/pair", method: "POST", body: body)
        return PairResult(nodeId: r["node_id"] as? String ?? "",
                          already: r["already"] as? Bool ?? false)
    }

    // PATCH /api/nodes/<node_id> {label} → {ok}
    func renameNode(nodeId: String, label: String) async throws {
        _ = try await request("/api/nodes/\(enc(nodeId))", method: "PATCH",
                              body: ["label": label])
    }

    // DELETE /api/nodes/<node_id> → {ok}
    func unpairNode(nodeId: String) async throws {
        _ = try await request("/api/nodes/\(enc(nodeId))", method: "DELETE")
    }

    // POST /api/nodes/<node_id>/ir/learn → تضع الوحدة بوضع التعلّم (تلتقط الضغطة القادمة)
    func nodeIrLearnStart(nodeId: String) async throws {
        _ = try await request("/api/nodes/\(enc(nodeId))/ir/learn", method: "POST", body: [:])
    }

    // GET /api/nodes/<node_id>/ir/last → {code, at} — آخر كود أشعة التقطته الوحدة
    func nodeIrLast(nodeId: String) async throws -> (code: String, at: String) {
        let r = try await request("/api/nodes/\(enc(nodeId))/ir/last")
        return (r["code"] as? String ?? "", r["at"] as? String ?? "")
    }
}
