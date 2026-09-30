import Foundation

private struct MemoryListResponse: Decodable {
    let items: [Row]?

    struct Row: Decodable {
        let id: String?
        let text: String?
        let type: String?
    }
}

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

private struct CreateConversationResponse: Decodable {
    let id: String?
}

private struct ConversationDetailResponse: Decodable {
    let title: String?
    let messages: [Row]?

    struct Row: Decodable {
        let role: String?
        let text: String?
    }
}

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

extension APIClient {
    /// نفس /api/agent بس SSE: `onChunk` بياخد النص التراكمي (ردود الأدوات بتيجي دفعة وحدة).
    /// `clientMsgId` is the idempotency key; only `.connection` errors are retryable.
    func sendMessageStreaming(
        _ text: String,
        conversationId: String? = nil,
        clientMsgId: String? = nil,
        onChunk: @MainActor @escaping (String) -> Void
    ) async throws -> (reply: String, imageURL: String?) {
        guard let url = URL(string: baseURL + "/api/agent/stream") else {
            throw APIError(message: "عنوان غير صالح")
        }
        let lang = await LanguageManager.shared.lang.rawValue
        var bodyDict: [String: Any] = ["message": text, "lang": lang]
        if let cid = conversationId, !cid.isEmpty { bodyDict["conversation_id"] = cid }
        if let key = clientMsgId, !key.isEmpty { bodyDict["client_msg_id"] = key }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 60
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let sentToken = token
        if let t = sentToken { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        req.httpBody = try JSONSerialization.data(withJSONObject: bodyDict)

        let bytes: URLSession.AsyncBytes
        let resp: URLResponse
        do {
            // No transport retry mid-stream; the caller resends with the same `clientMsgId`.
            // `req.timeoutInterval` is the idle bound here.
            (bytes, resp) = try await APIClient.session.bytes(for: req)
        } catch let urlError as URLError {
            // Cancellation keeps its identity (see `perform`).
            if urlError.code == .cancelled { throw urlError }
            throw APIError(message: "تعذّر الاتصال بالخادم. تأكد من الإنترنت وحاول مرة ثانية.", kind: .connection)
        }
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401 {
            // Same rule as `perform`: only the current session dying signs out.
            if let s = sentToken, s == token { onUnauthorized?() }
            throw APIError(message: "انتهت الجلسة، سجّل دخولك من جديد.", kind: .unauthorized)
        }
        if code >= 400 {
            // ردود الخطأ ما بتنستريم — نقرأ الجسم الصغير عادي.
            var data = Data()
            for try await byte in bytes { data.append(byte) }
            let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
            throw APIError(message: (json["message"] as? String) ?? (json["error"] as? String) ?? "خطأ \(code)",
                           code: json["error"] as? String, kind: .server)
        }

        var finalReply = ""
        var sawDone = false
        var imageURL: String?
        do {
            for try await line in bytes.lines {
                guard line.hasPrefix("data: "),
                      let data = line.dropFirst("data: ".count).data(using: .utf8),
                      let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                else { continue }
                if let err = obj["error"] as? String {
                    let message = (obj["message"] as? String)
                        ?? (err == "internal_error" ? "معلش، صار خطأ." : err)
                    throw APIError(message: message, code: err, kind: .server)
                }
                if obj["done"] as? Bool == true {
                    finalReply = obj["reply"] as? String ?? finalReply
                    imageURL = obj["image_url"] as? String
                    sawDone = true
                    break
                }
                if let partial = obj["text"] as? String {
                    await onChunk(partial)
                }
            }
        } catch let urlError as URLError {
            if urlError.code == .cancelled { throw urlError }
            throw APIError(message: "انقطع الرد قبل ما يكمل. جرّب مرة ثانية.", kind: .connection)
        }
        // A stream cut before `done` is a connection failure: the caller retries with the same key.
        if !sawDone {
            throw APIError(message: "انقطع الرد قبل ما يكمل. جرّب مرة ثانية.", kind: .connection)
        }
        return (finalReply, imageURL)
    }

    // MARK: - سجل المحادثات

    func listConversations() async throws -> [ConversationMeta] {
        let r: ConversationListResponse = try await fetch("/api/conversations")
        return (r.items ?? []).map {
            ConversationMeta(id: $0.id ?? "",
                             title: $0.title ?? "",
                             updatedAt: $0.updatedAt ?? "")
        }
    }

    func createConversation() async throws -> String {
        let r: CreateConversationResponse = try await fetch("/api/conversations", method: "POST",
                                                            body: [String: String]())
        guard let id = r.id, !id.isEmpty else {
            throw APIError(message: "تعذّر إنشاء المحادثة")
        }
        return id
    }

    func getConversation(id: String) async throws -> (title: String, messages: [ChatMessage]) {
        let r: ConversationDetailResponse = try await fetch("/api/conversations/\(id)")
        let msgs = (r.messages ?? []).compactMap { m -> ChatMessage? in
            guard let role = m.role, let text = m.text else { return nil }
            return ChatMessage(role: role, text: text)
        }
        return (r.title ?? "", msgs)
    }

    func appendMessage(cid: String, role: String, text: String) async throws {
        try await send("/api/conversations/\(cid)/messages", method: "POST",
                       body: ["role": role, "text": text])
    }

    func renameConversation(id: String, title: String) async throws {
        try await send("/api/conversations/\(id)", method: "PATCH",
                       body: ["title": title])
    }

    func deleteConversation(id: String) async throws {
        try await send("/api/conversations/\(id)", method: "DELETE")
    }

    func searchConversations(q: String) async throws -> [ConversationHit] {
        let r: ConversationSearchResponse = try await fetch("/api/conversations/search?q=\(enc(q))")
        return (r.items ?? []).map {
            ConversationHit(id: $0.id ?? "",
                            title: $0.title ?? "",
                            snippet: $0.snippet ?? "",
                            updatedAt: $0.updatedAt ?? "")
        }
    }

    // MARK: - الذاكرة

    func getMemory() async throws -> [MemoryFact] {
        let r: MemoryListResponse = try await fetch("/api/memory")
        return (r.items ?? []).map {
            MemoryFact(id: $0.id ?? "",
                       text: $0.text ?? "",
                       type: $0.type ?? "general")
        }
    }

    func addMemory(text: String) async throws {
        try await send("/api/memory", method: "POST", body: ["text": text])
    }

    func updateMemory(id: String, text: String) async throws {
        try await send("/api/memory/\(id)", method: "PATCH", body: ["text": text])
    }

    func deleteMemory(id: String) async throws {
        try await send("/api/memory/\(id)", method: "DELETE")
    }
}
