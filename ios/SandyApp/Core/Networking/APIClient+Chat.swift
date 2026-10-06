import Foundation

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
        let attachments: [ChatAttachment]?
    }
}

private struct AttachmentSaved: Decodable { let item: ChatAttachment? }

/// A message as the history keeps it.
private struct MessageAppend: Encodable {
    let role: String
    let text: String
    let attachments: [ChatAttachment]?
    /// The send's id on a user line: a rewind takes back that line's turn and no other.
    let clientMsgId: String?

    enum CodingKeys: String, CodingKey {
        case role, text, attachments
        case clientMsgId = "client_msg_id"
    }
}

/// Reports how much of an upload has gone out (0…1).
private final class UploadProgress: NSObject, URLSessionTaskDelegate {
    let report: @Sendable (Double) -> Void
    init(_ report: @escaping @Sendable (Double) -> Void) { self.report = report }

    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64,
                    totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        guard totalBytesExpectedToSend > 0 else { return }
        report(Double(totalBytesSent) / Double(totalBytesExpectedToSend))
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
        attachments: [ChatAttachment] = [],
        onStep: (@MainActor (String) -> Void)? = nil,
        onChunk: @MainActor @escaping (String) -> Void
    ) async throws -> (reply: String, image: ChatAttachment?) {
        guard let url = URL(string: baseURL + "/api/agent/stream") else {
            throw APIError(message: "عنوان غير صالح")
        }
        let lang = await LanguageManager.shared.lang.rawValue
        var bodyDict: [String: Any] = ["message": text, "lang": lang]
        if let cid = conversationId, !cid.isEmpty { bodyDict["conversation_id"] = cid }
        if let key = clientMsgId, !key.isEmpty { bodyDict["client_msg_id"] = key }
        if !attachments.isEmpty { bodyDict["attachments"] = attachments.map(\.id) }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 60
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let sentToken = token
        if let t = sentToken { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        req.setValue(TimeZone.current.identifier, forHTTPHeaderField: "X-Timezone")
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
        var image: ChatAttachment?
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
                    // A picture Sandy drew, kept on the server as an attachment.
                    if let drawn = obj["image"] as? [String: Any], let id = drawn["id"] as? String {
                        image = ChatAttachment(id: id, kind: "image", name: drawn["name"] as? String ?? "")
                    }
                    sawDone = true
                    break
                }
                // A tool about to run, so the screen can say what Sandy is doing.
                if let step = obj["step"] as? String {
                    await onStep?(step)
                } else if let partial = obj["text"] as? String {
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
        return (finalReply, image)
    }

    // MARK: - المرفقات

    /// Uploads a photo or a document for the chat; `progress` gets 0…1 as it goes out.
    /// A refusal (too big, a type Sandy cannot read) comes back with the line to show.
    func uploadAttachment(_ data: Data, name: String, mime: String,
                          progress: @escaping @Sendable (Double) -> Void) async throws -> ChatAttachment {
        guard let url = URL(string: baseURL + "/api/attachments") else {
            throw APIError(message: "عنوان غير صالح")
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 120
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        req.setValue(TimeZone.current.identifier, forHTTPHeaderField: "X-Timezone")
        let body = try JSONSerialization.data(withJSONObject: [
            "data": data.base64EncodedString(), "name": name, "mime": mime])
        let (out, resp): (Data, URLResponse)
        do {
            (out, resp) = try await APIClient.session.upload(for: req, from: body,
                                                             delegate: UploadProgress(progress))
        } catch let urlError as URLError {
            if urlError.code == .cancelled { throw urlError }
            throw APIError(message: "تعذّر الاتصال بالخادم. تأكد من الإنترنت وحاول مرة ثانية.", kind: .connection)
        }
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: out)) as? [String: Any] ?? [:]
        guard code < 400, let saved = try? JSONDecoder().decode(AttachmentSaved.self, from: out),
              let item = saved.item else {
            throw APIError(message: json["message"] as? String ?? "خطأ \(code)",
                           code: json["error"] as? String, kind: .server)
        }
        return item
    }

    /// An attachment's bytes (a photo to show, a drawn image to save).
    func attachmentData(id: String) async throws -> Data {
        try await rawGet("/api/attachments/\(id)/file", timeout: 60)
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
            guard let role = m.role else { return nil }
            let files = m.attachments ?? []
            guard !(m.text ?? "").isEmpty || !files.isEmpty else { return nil }
            return ChatMessage(role: role, text: m.text ?? "", attachments: files)
        }
        return (r.title ?? "", msgs)
    }

    func appendMessage(cid: String, role: String, text: String,
                       attachments: [ChatAttachment] = [], clientMsgId: String? = nil) async throws {
        try await send("/api/conversations/\(cid)/messages", method: "POST",
                       body: MessageAppend(role: role, text: text,
                                           attachments: attachments.isEmpty ? nil : attachments,
                                           clientMsgId: clientMsgId))
    }

    /// Drops the last reply (and, unless `keepUser`, the line it answered) on the server and
    /// in Sandy's memory of the thread, before a regenerate or an edited resend.
    func rewindConversation(id: String, keepUser: Bool) async throws {
        try await send("/api/conversations/\(id)/rewind", method: "POST", body: ["keep_user": keepUser])
    }

    /// The reply was stopped after `partial`: the server stops the turn (if still running) and
    /// Sandy remembers only what was shown, marked as cut.
    func stopReply(conversationId: String, partial: String, clientMsgId: String) async throws {
        try await send("/api/conversations/\(conversationId)/stop", method: "POST",
                       body: ["partial": partial, "client_msg_id": clientMsgId])
    }

    func renameConversation(id: String, title: String) async throws {
        try await send("/api/conversations/\(id)", method: "PATCH",
                       body: ["title": title])
    }

    func deleteConversation(id: String) async throws {
        try await send("/api/conversations/\(id)", method: "DELETE")
    }

    func searchConversations(q: String) async throws -> [ConversationHit] {
        let r: ConversationSearchResponse = try await fetch("/api/conversations/search?q=\(URLEscape.query(q))")
        return (r.items ?? []).map {
            ConversationHit(id: $0.id ?? "",
                            title: $0.title ?? "",
                            snippet: $0.snippet ?? "",
                            updatedAt: $0.updatedAt ?? "")
        }
    }

    // MARK: - صوت ساندي

    /// صوت ساندي (WAV من جيميني) لنصّ معيّن؛ بايتات خام، فبيضل على URLSession مباشرة.
    func synthesizeVoice(text: String, mood: String = "neutral") async throws -> Data {
        guard let url = URL(string: baseURL + "/api/voice/tts") else {
            throw APIError(message: "عنوان غير صالح")
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        req.setValue(TimeZone.current.identifier, forHTTPHeaderField: "X-Timezone")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["text": text, "mood": mood])
        let (data, resp) = try await APIClient.sendWithRetry(
            req, method: req.httpMethod ?? "GET")
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code >= 400 { throw APIError(message: "صوت غير متاح (\(code))") }
        return data
    }
}
