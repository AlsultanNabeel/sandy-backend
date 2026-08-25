import Foundation

/// رد قائمة الذاكرة: عناصر {id, text, type}.
private struct MemoryListResponse: Decodable {
    let items: [Row]?

    struct Row: Decodable {
        let id: String?
        let text: String?
        let type: String?
    }
}

/// رد الخط الزمني: أحداث موحّدة {type, id, title, subtitle, ts, done}.
private struct TimelineListResponse: Decodable {
    let items: [Row]?

    struct Row: Decodable {
        let id: String?
        let type: String?
        let title: String?
        let subtitle: String?
        let ts: String?
        let done: Bool?
    }
}

/// رد قائمة المحادثات: عناصر {id, title, updated_at}.
private struct ConversationListResponse: Decodable {
    let items: [Row]?

    struct Row: Decodable {
        let id: String?
        let title: String?
        let updatedAt: String?

        enum CodingKeys: String, CodingKey {
            case id, title
            case updatedAt = "updated_at"
        }
    }
}

/// رد إنشاء محادثة: المعرّف الجديد.
private struct CreateConversationResponse: Decodable {
    let id: String?
}

/// رد فتح محادثة: العنوان + الرسائل {role, text}.
private struct ConversationDetailResponse: Decodable {
    let title: String?
    let messages: [Row]?

    struct Row: Decodable {
        let role: String?
        let text: String?
    }
}

/// رد بحث المحادثات: عناصر {id, title, snippet, updated_at}.
private struct ConversationSearchResponse: Decodable {
    let items: [Row]?

    struct Row: Decodable {
        let id: String?
        let title: String?
        let snippet: String?
        let updatedAt: String?

        enum CodingKeys: String, CodingKey {
            case id, title, snippet
            case updatedAt = "updated_at"
        }
    }
}

/// رد الوكيل غير المُستريم: نص الرد فقط (الحقول الأخرى يتجاهلها الفك).
private struct AgentReplyResponse: Decodable {
    let reply: String?
}

extension APIClient {
    func sendMessage(_ text: String, conversationId: String? = nil) async throws -> String {
        // نرسل لغة المستخدم الحالية (عربي/إنجليزي) حتى ترد ساندي بنفس اللغة.
        let lang = await LanguageManager.shared.lang.rawValue
        var body: [String: String] = ["message": text, "lang": lang]
        // سيشن الشات — تخلّي ساندي تتذكّر هالمحادثة لحالها بلا ما تخلط المواضيع.
        if let cid = conversationId, !cid.isEmpty { body["conversation_id"] = cid }
        let r: AgentReplyResponse = try await fetch("/api/agent", method: "POST", body: body)
        return r.reply ?? "…"
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
            // No retry on a stream: a reply that is half-delivered must not be
            // started over. `req.timeoutInterval` is the idle bound here.
            (bytes, resp) = try await APIClient.session.bytes(for: req)
        } catch let urlError as URLError {
            // Cancellation keeps its identity — a send superseded by a newer
            // one is a decision, not a failure, and collapsing it here is the
            // spurious "couldn't load" notice `perform` has a comment about.
            if urlError.code == .cancelled { throw urlError }
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
        let r: ConversationListResponse = try await fetch("/api/conversations")
        return (r.items ?? []).map {
            ConversationMeta(id: $0.id ?? "",
                             title: $0.title ?? "",
                             updatedAt: $0.updatedAt ?? "")
        }
    }

    // POST /api/conversations → {"id"}
    func createConversation() async throws -> String {
        let r: CreateConversationResponse = try await fetch("/api/conversations", method: "POST",
                                                            body: [String: String]())
        guard let id = r.id, !id.isEmpty else {
            throw APIError(message: "تعذّر إنشاء المحادثة")
        }
        return id
    }

    // GET /api/conversations/<id> → {"title","messages":[{role,text,ts}]}
    func getConversation(id: String) async throws -> (title: String, messages: [ChatMessage]) {
        let r: ConversationDetailResponse = try await fetch("/api/conversations/\(id)")
        let msgs = (r.messages ?? []).compactMap { m -> ChatMessage? in
            guard let role = m.role, let text = m.text else { return nil }
            return ChatMessage(role: role, text: text)
        }
        return (r.title ?? "", msgs)
    }

    // POST /api/conversations/<id>/messages {role,text}
    func appendMessage(cid: String, role: String, text: String) async throws {
        try await send("/api/conversations/\(cid)/messages", method: "POST",
                       body: ["role": role, "text": text])
    }

    // PATCH /api/conversations/<id> {title} → {"ok":true} — إعادة تسمية المحادثة.
    func renameConversation(id: String, title: String) async throws {
        try await send("/api/conversations/\(id)", method: "PATCH",
                       body: ["title": title])
    }

    // DELETE /api/conversations/<id>
    func deleteConversation(id: String) async throws {
        try await send("/api/conversations/\(id)", method: "DELETE")
    }

    // GET /api/conversations/search?q= → {"items":[{id,title,snippet,updated_at}]}
    func searchConversations(q: String) async throws -> [ConversationHit] {
        let r: ConversationSearchResponse = try await fetch("/api/conversations/search?q=\(enc(q))")
        return (r.items ?? []).map {
            ConversationHit(id: $0.id ?? "",
                            title: $0.title ?? "",
                            snippet: $0.snippet ?? "",
                            updatedAt: $0.updatedAt ?? "")
        }
    }

    // MARK: - الذاكرة (اللي ساندي متذكّراه عنك)

    // GET /api/memory → {"items":[{id,text,type}]}
    func getMemory() async throws -> [MemoryFact] {
        let r: MemoryListResponse = try await fetch("/api/memory")
        return (r.items ?? []).map {
            MemoryFact(id: $0.id ?? "",
                       text: $0.text ?? "",
                       type: $0.type ?? "general")
        }
    }

    // POST /api/memory {text} → {"ok":true,"id"} — احفظ معلومة جديدة عنك.
    func addMemory(text: String) async throws {
        try await send("/api/memory", method: "POST", body: ["text": text])
    }

    // PATCH /api/memory/<id> {text} → {"ok":bool} — عدّل نص معلومة.
    func updateMemory(id: String, text: String) async throws {
        try await send("/api/memory/\(id)", method: "PATCH", body: ["text": text])
    }

    // DELETE /api/memory/<id>
    func deleteMemory(id: String) async throws {
        try await send("/api/memory/\(id)", method: "DELETE")
    }

    // MARK: - الخط الزمني (سجل النشاط الموحّد)

    // GET /api/timeline → {"items":[{type,id,title,subtitle,ts,done}]}
    func getTimeline() async throws -> [TimelineEvent] {
        let r: TimelineListResponse = try await fetch("/api/timeline")
        return (r.items ?? []).map {
            TimelineEvent(id: $0.id ?? "",
                          type: $0.type ?? "",
                          title: $0.title ?? "",
                          subtitle: $0.subtitle ?? "",
                          ts: $0.ts ?? "",
                          done: $0.done ?? false)
        }
    }
}
