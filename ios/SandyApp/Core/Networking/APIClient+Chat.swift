import Foundation

extension APIClient {
    func sendMessage(_ text: String, conversationId: String? = nil) async throws -> String {
        // نرسل لغة المستخدم الحالية (عربي/إنجليزي) حتى ترد ساندي بنفس اللغة.
        let lang = await LanguageManager.shared.lang.rawValue
        var body: [String: Any] = ["message": text, "lang": lang]
        // سيشن الشات — تخلّي ساندي تتذكّر هالمحادثة لحالها بلا ما تخلط المواضيع.
        if let cid = conversationId, !cid.isEmpty { body["conversation_id"] = cid }
        let r = try await request("/api/agent", method: "POST", body: body)
        return r["reply"] as? String ?? "…"
    }

    /// نفس /api/agent بس ستريمنغ (SSE) — ينادي onChunk بالنص التراكمي أول
    /// بأول (رد الدردشة العادي بس؛ ردود الأدوات زي "أضف مهمة" ما فيها أجزاء
    /// تتستريم، بترجع دفعة وحدة بآخر حدث). يرجع الرد النهائي + رابط صورة لو في.
    func sendMessageStreaming(
        _ text: String,
        conversationId: String? = nil,
        onChunk: @MainActor @escaping (String) -> Void
    ) async throws -> (reply: String, imageURL: String?) {
        guard let url = URL(string: baseURL + "/api/agent/stream") else {
            throw APIError(message: "عنوان غير صالح")
        }
        let lang = await LanguageManager.shared.lang.rawValue
        var bodyDict: [String: Any] = ["message": text, "lang": lang]
        if let cid = conversationId, !cid.isEmpty { bodyDict["conversation_id"] = cid }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 60
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        req.httpBody = try JSONSerialization.data(withJSONObject: bodyDict)

        let bytes: URLSession.AsyncBytes
        let resp: URLResponse
        do {
            (bytes, resp) = try await URLSession.shared.bytes(for: req)
        } catch is URLError {
            throw APIError(message: "تعذّر الاتصال بالخادم. تأكد من الإنترنت وحاول مرة ثانية.", kind: .connection)
        }
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401 {
            onUnauthorized?()
            throw APIError(message: "انتهت الجلسة، سجّل دخولك من جديد.", kind: .unauthorized)
        }
        if code >= 400 {
            // ردود الخطأ ما بتنستريم — نقرأ الجسم الصغير عادي.
            var data = Data()
            for try await byte in bytes { data.append(byte) }
            let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
            throw APIError(message: (json["error"] as? String) ?? "خطأ \(code)", kind: .server)
        }

        var finalReply = ""
        var imageURL: String?
        for try await line in bytes.lines {
            guard line.hasPrefix("data: "),
                  let data = line.dropFirst("data: ".count).data(using: .utf8),
                  let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            else { continue }
            if let err = obj["error"] as? String {
                throw APIError(message: err == "internal_error" ? "معلش، صار خطأ." : err, kind: .server)
            }
            if obj["done"] as? Bool == true {
                finalReply = obj["reply"] as? String ?? finalReply
                imageURL = obj["image_url"] as? String
                break
            }
            if let partial = obj["text"] as? String {
                await onChunk(partial)
            }
        }
        return (finalReply, imageURL)
    }

    // MARK: - سجل المحادثات (متعدد السيشنات)

    // GET /api/conversations → {"items":[{id,title,updated_at}]}
    func listConversations() async throws -> [ConversationMeta] {
        let r = try await request("/api/conversations")
        return (r["items"] as? [[String: Any]] ?? []).map {
            ConversationMeta(id: $0["id"] as? String ?? "",
                             title: $0["title"] as? String ?? "",
                             updatedAt: $0["updated_at"] as? String ?? "")
        }
    }

    // POST /api/conversations → {"id"}
    func createConversation() async throws -> String {
        let r = try await request("/api/conversations", method: "POST", body: [:])
        guard let id = r["id"] as? String, !id.isEmpty else {
            throw APIError(message: "تعذّر إنشاء المحادثة")
        }
        return id
    }

    // GET /api/conversations/<id> → {"title","messages":[{role,text,ts}]}
    func getConversation(id: String) async throws -> (title: String, messages: [ChatMessage]) {
        let r = try await request("/api/conversations/\(id)")
        let msgs = (r["messages"] as? [[String: Any]] ?? []).compactMap { m -> ChatMessage? in
            guard let role = m["role"] as? String, let text = m["text"] as? String else { return nil }
            return ChatMessage(role: role, text: text)
        }
        return (r["title"] as? String ?? "", msgs)
    }

    // POST /api/conversations/<id>/messages {role,text}
    func appendMessage(cid: String, role: String, text: String) async throws {
        _ = try await request("/api/conversations/\(cid)/messages", method: "POST",
                              body: ["role": role, "text": text])
    }

    // PATCH /api/conversations/<id> {title} → {"ok":true} — إعادة تسمية المحادثة.
    func renameConversation(id: String, title: String) async throws {
        _ = try await request("/api/conversations/\(id)", method: "PATCH",
                              body: ["title": title])
    }

    // DELETE /api/conversations/<id>
    func deleteConversation(id: String) async throws {
        _ = try await request("/api/conversations/\(id)", method: "DELETE")
    }

    // GET /api/conversations/search?q= → {"items":[{id,title,snippet,updated_at}]}
    func searchConversations(q: String) async throws -> [ConversationHit] {
        let r = try await request("/api/conversations/search?q=\(enc(q))")
        return (r["items"] as? [[String: Any]] ?? []).map {
            ConversationHit(id: $0["id"] as? String ?? "",
                            title: $0["title"] as? String ?? "",
                            snippet: $0["snippet"] as? String ?? "",
                            updatedAt: $0["updated_at"] as? String ?? "")
        }
    }

    // MARK: - الذاكرة (اللي ساندي متذكّراه عنك)

    // GET /api/memory → {"items":[{id,text,type}]}
    func getMemory() async throws -> [MemoryFact] {
        let r = try await request("/api/memory")
        return (r["items"] as? [[String: Any]] ?? []).map {
            MemoryFact(id: $0["id"] as? String ?? "",
                       text: $0["text"] as? String ?? "",
                       type: $0["type"] as? String ?? "general")
        }
    }

    // POST /api/memory {text} → {"ok":true,"id"} — احفظ معلومة جديدة عنك.
    func addMemory(text: String) async throws {
        _ = try await request("/api/memory", method: "POST", body: ["text": text])
    }

    // PATCH /api/memory/<id> {text} → {"ok":bool} — عدّل نص معلومة.
    func updateMemory(id: String, text: String) async throws {
        _ = try await request("/api/memory/\(id)", method: "PATCH", body: ["text": text])
    }

    // DELETE /api/memory/<id>
    func deleteMemory(id: String) async throws {
        _ = try await request("/api/memory/\(id)", method: "DELETE")
    }

    // MARK: - الخط الزمني (سجل النشاط الموحّد)

    // GET /api/timeline → {"items":[{type,id,title,subtitle,ts,done}]}
    func getTimeline() async throws -> [TimelineEvent] {
        let r = try await request("/api/timeline")
        return (r["items"] as? [[String: Any]] ?? []).map {
            TimelineEvent(id: $0["id"] as? String ?? "",
                          type: $0["type"] as? String ?? "",
                          title: $0["title"] as? String ?? "",
                          subtitle: $0["subtitle"] as? String ?? "",
                          ts: $0["ts"] as? String ?? "",
                          done: $0["done"] as? Bool ?? false)
        }
    }
}
