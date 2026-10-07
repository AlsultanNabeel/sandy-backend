import SwiftUI

/// يملك المحادثة الحالية + سجل السيشنات. الإرسال يجري في مهمة يملكها الستور
/// (محصّنة ضد إلغاء الإيماءة)، وكل تبادل يُحفظ تلقائيًا بالباك-إند. المرحلة (أ):
/// محادثات متعددة + حفظ + سجل + بحث نصي؛ المرحلة (ب) تضيف التلخيص والاسترجاع.
@MainActor
final class ChatStore: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var sending = false
    /// From send until the reply is complete (`sending` ends at the first word): the stop button.
    @Published private(set) var replying = false
    /// From «stop» until the server has it: the stopped turn may still be running and save last,
    /// so «write it again» and «edit» wait.
    @Published private(set) var stopping = false
    /// What Sandy is doing right now («عم ضيف للقائمة…»), empty while she only talks.
    @Published var activity = ""
    @Published var errorMessage = ""
    @Published var conversations: [ConversationMeta] = []
    /// nil = محادثة جديدة "كسولة": معرّفها بيتولّد محليًا مع أول رسالة، والخادم
    /// بينشئها مع أول طلب بيحملها (بلا محادثات فاضية وبلا رحلة إنشاء منفصلة).
    @Published private(set) var currentID: String?
    /// The field holds the last line, being edited; sending replaces it and its reply. It is
    /// this conversation's: another one opened, or a new one, ends it (it used to go along and
    /// drop the other conversation's last line, or the message itself in an empty one).
    @Published var editingLast = false

    private var sendTask: Task<String?, Never>?
    /// Bumped per send. A superseded send's cleanup must not clear `sending`
    /// for the send that replaced it.
    private var sendGeneration = 0

    /// Which account this store is showing. `UserDefaults` is one store for the
    /// whole device, so a bare `"sandy_current_conv"` is the *previous*
    /// account's conversation id sitting there when the next one signs in. It
    /// never leaked a message — the server scopes conversations and would
    /// refuse the read — but it did decide whether the new account's latest
    /// conversation opened on its own, from an id that was not theirs.
    private var userScope = ""
    private var currentKey: String { "sandy_current_conv." + userScope }

    /// Called at the top of `bootstrap`. When the account has changed, nothing
    /// on screen or in this store belongs to the one now signed in.
    private func adoptScope(_ api: APIClient) {
        let uid = api.currentUserId ?? ""
        guard uid != userScope else { return }
        userScope = uid
        sendTask?.cancel()
        sendGeneration += 1
        messages = []
        conversations = []
        currentID = nil
        editingLast = false
        errorMessage = ""
        sending = false
        replying = false
    }

    /// عند فتح التبويب: يحمّل السجل، ويستكمل آخر محادثة من اليوم أو يبدأ نظيفة.
    func bootstrap(api: APIClient) async {
        // Before the early return below, not after: a different account signing
        // in on this phone is exactly the case where there *is* a conversation
        // on screen and it must not be kept.
        adoptScope(api)
        // لو في محادثة معروضة أصلًا (رجعنا للتبويب) لا نعيد شيئًا — ولا حتى
        // القائمة: ورقة السجل بتحمّلها بنفسها لما تنفتح.
        if currentID != nil || !messages.isEmpty { return }
        await loadList(api: api)
        let savedID = UserDefaults.standard.string(forKey: currentKey)
        if let latest = conversations.first, isToday(latest.updatedAt),
           savedID == nil || savedID == latest.id {
            await open(api: api, id: latest.id)
        }
    }

    func loadList(api: APIClient) async {
        if conversations.isEmpty,
           let cached = DiskCache.load([ConversationMeta].self, key: "chat.list", userId: api.currentUserId) {
            conversations = cached
        }
        if let list = try? await api.listConversations() {
            conversations = list
            DiskCache.save(list, key: "chat.list", userId: api.currentUserId)
        }
    }

    /// One saved line of a conversation, for opening it offline.
    private struct Line: Codable {
        let role: String
        let text: String
        var attachments: [ChatAttachment]?
    }

    private func saveLines(_ api: APIClient, id: String) {
        DiskCache.save(messages.map { Line(role: $0.role, text: $0.text, attachments: $0.attachments) },
                       key: "chat." + id, userId: api.currentUserId)
    }

    func open(api: APIClient, id: String) async {
        // The conversation on screen, its reply still coming: it stays as it is.
        if id == currentID && replying { return }
        leave(api)
        if let r = try? await api.getConversation(id: id) {
            messages = r.messages
            saveLines(api, id: id)
        } else if let lines = DiskCache.load([Line].self, key: "chat." + id, userId: api.currentUserId) {
            messages = lines.map { ChatMessage(role: $0.role, text: $0.text, attachments: $0.attachments ?? []) }
        } else {
            return
        }
        errorMessage = ""
        if id != currentID { editingLast = false }
        currentID = id
        UserDefaults.standard.set(id, forKey: currentKey)
    }

    /// A reply still coming belongs to the conversation being left: it stops there and what
    /// arrived is kept in it, as with «stop». Cancelled bare, nothing of it was saved and the
    /// question was left with no answer.
    private func leave(_ api: APIClient) {
        if replying { stop(api: api) } else { sendTask?.cancel() }
    }

    /// محادثة جديدة فورية (كسولة): يصفّي العرض، والإنشاء الفعلي عند أول رسالة.
    func startNew(api: APIClient) {
        leave(api)
        messages = []
        editingLast = false
        errorMessage = ""
        currentID = nil
        UserDefaults.standard.removeObject(forKey: currentKey)
    }

    /// Off the history now, deleted on the server when the «تراجع» offer ends.
    func delete(api: APIClient, id: String) async {
        guard let idx = conversations.firstIndex(where: { $0.id == id }) else { return }
        let removed = conversations.remove(at: idx)
        if id == currentID { startNew(api: api) }
        UndoCenter.shared.offer(
            String(format: LanguageManager.shared.s("blocks.deletedToast"), removed.title),
            icon: "trash",
            undo: { [weak self] in
                guard let self, !self.conversations.contains(where: { $0.id == id }) else { return }
                self.conversations.insert(removed, at: min(idx, self.conversations.count))
            },
            commit: { [weak self] in
                try? await api.deleteConversation(id: id)
                await self?.loadList(api: api)
            })
    }

    /// إعادة تسمية محادثة (تحديث متفائل للعنوان) ثم مصالحة مع السيرفر.
    func rename(api: APIClient, id: String, title: String) async {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        if let i = conversations.firstIndex(where: { $0.id == id }) {
            conversations[i].title = trimmed
        }
        try? await api.renameConversation(id: id, title: trimmed)
        await loadList(api: api)
    }

    /// What the error line calls the user (their preferred name), set by the chat screen.
    var userName = ""
    private var lastErrorVariant = -1
    /// The reply streaming now, so «إيقاف» can keep what already arrived.
    private var streamingID: UUID?
    private var streamingCid: String?
    private var streamingCmid: String?

    /// يرسل، يخزّن السؤال والرد، ويرجّع رد ساندي (ليقرأه الـView بالصوت).
    /// `appendUser: false` answers the line already last (regenerate); with `resendID` that
    /// line is sent again as the message it was («أعد المحاولة»).
    func send(api: APIClient, text: String, attachments: [ChatAttachment] = [],
              appendUser: Bool = true, resendID: String? = nil) async -> String? {
        sendTask?.cancel()
        sendGeneration += 1
        let generation = sendGeneration
        // مفتاح الرسالة: نفسه بكل محاولة، فالخادم ما بيشغّل الدور مرتين.
        let clientMsgID = resendID ?? Self.newID()
        let savesUser = appendUser || resendID != nil
        if appendUser {
            messages.append(ChatMessage(role: "user", text: text, attachments: attachments,
                                        clientMsgId: clientMsgID))
        }
        let userLine = messages.last { $0.role == "user" }
        let userLineID = userLine?.id
        // A regenerate answers the line with the attachments it had.
        let attachments = appendUser ? attachments : (userLine?.attachments ?? [])
        sending = true
        replying = true
        errorMessage = ""
        Haptics.play(.send)
        // محادثة جديدة: المعرّف منّا (uuid) والخادم بينشئها مع أول رسالة — بلا
        // رحلة POST قبل أول حرف من الرد.
        let cid: String
        if let id = currentID {
            cid = id
        } else {
            cid = Self.newID()
            currentID = cid
            UserDefaults.standard.set(cid, forKey: currentKey)
        }
        // No bubble of this reply yet: one kept from the reply before would be what «stop» saves.
        streamingID = nil
        streamingCid = cid
        streamingCmid = clientMsgID
        let t = Task { @MainActor () -> String? in
            defer {
                if generation == sendGeneration {
                    sending = false
                    replying = false
                    activity = ""
                    streamingID = nil
                }
            }
            // حفظ رسالة المستخدم وتشغيل ساندي مستقلّان — /api/agent بياخد نص
            // الرسالة من الطلب نفسه، مش من القاعدة، فما داعي ننتظر الحفظ. مهمة
            // منفصلة: الرسالة بتنحفظ حتى لو الإرسال اتلغى أو فشل.
            let saveUser = Task {
                // Sent again under its id, the server keeps the line once.
                if savesUser {
                    try? await api.appendMessage(cid: cid, role: "user", text: text, attachments: attachments,
                                                 clientMsgId: clientMsgID)
                }
            }
            // By id, not index: `messages` can be replaced mid-stream (new
            // chat, another conversation opened), and a stored index then
            // points past the end — a crash on the next chunk.
            var sandyID: UUID?
            // أطول نص وصل بأي محاولة — لو فشلت كل المحاولات بنحتفظ فيه بدل ما نمسحه.
            var bestPartial = ""
            do {
                let reply: String
                var drawn: [ChatAttachment] = []
                do {
                    let result = try await withConnectionRetry(onRetry: {
                        // المحاولة الجديدة بتبدأ الرد من أوله: نشيل الفقاعة
                        // الجزئية ونرجّع مؤشّر الكتابة، فما يتكرّر النص.
                        if let id = sandyID { self.messages.removeAll { $0.id == id } }
                        sandyID = nil
                        if generation == self.sendGeneration { self.sending = true }
                    }) {
                        // نمرّر سيشن المحادثة فتتذكّرها ساندي مستقلة عن باقي محادثاتك.
                        // أول قطعة توصل تستبدل مؤشّر الكتابة بفقاعة نصّية تكبر تدريجياً —
                        // ردود الأدوات (زي "أضف مهمة") ما فيها قطع، بترجع دفعة وحدة بالنهاية.
                        try await api.sendMessageStreaming(text, conversationId: cid,
                                                           clientMsgId: clientMsgID,
                                                           attachments: attachments,
                                                           onStep: { [weak self] step in
                            guard let self, generation == self.sendGeneration else { return }
                            self.activity = ChatStep.label(step)
                        }) { [weak self] partial in
                            // Generation as well as cancellation. Cancellation
                            // is cooperative and observed at the next check, so
                            // between `sendTask?.cancel()` and this closure
                            // noticing, a chunk of the old conversation's reply
                            // can still arrive — and by then `messages` is the
                            // new conversation's. The generation is set
                            // synchronously by whoever superseded this send, so
                            // it is already false on the very first late chunk.
                            guard let self, !Task.isCancelled,
                                  generation == self.sendGeneration else { return }
                            if partial.count > bestPartial.count { bestPartial = partial }
                            if let id = sandyID, let idx = self.messages.firstIndex(where: { $0.id == id }) {
                                self.messages[idx].text = partial
                            } else if sandyID == nil {
                                self.sending = false
                                let bubble = ChatMessage(role: "sandy", text: partial)
                                sandyID = bubble.id
                                self.streamingID = bubble.id
                                self.streamingCid = cid
                                self.messages.append(bubble)
                            }
                        }
                    }
                    reply = result.reply
                    drawn = result.image.map { [$0] } ?? []
                } catch let e as APIError where e.kind == .connection && !bestPartial.isEmpty {
                    // كل المحاولات انقطعت بس وصل جزء من الرد: نحتفظ فيه.
                    reply = bestPartial
                }
                try Task.checkCancellation()
                if let id = sandyID, let idx = messages.firstIndex(where: { $0.id == id }) {
                    messages[idx].text = reply
                    messages[idx].attachments = drawn
                } else if sandyID == nil {
                    messages.append(ChatMessage(role: "sandy", text: reply, attachments: drawn))
                }
                saveLines(api, id: cid)
                // حفظ الرد وتحديث القائمة بالخلفية — الرد ظاهر، وصوت ساندي ما
                // بيستنّاهم. بالترتيب: رسالة المستخدم قبل الرد (منها العنوان).
                Task {
                    _ = await saveUser.value
                    try? await api.appendMessage(cid: cid, role: "sandy", text: reply, attachments: drawn)
                    await self.loadList(api: api)
                }
                Announce.say(String(format: LanguageManager.shared.s("a11y.replyArrived"), reply))
                // A reply may have added or changed things the other tabs show.
                NotificationCenter.default.post(name: .sandyBlocksChanged, object: nil)
                ReviewPrompter.shared.noteReply()
                return reply
            } catch {
                if !error.isCancellation {
                    // The line itself is marked, with «أعد المحاولة» on it.
                    if let id = userLineID, let idx = messages.firstIndex(where: { $0.id == id }) {
                        messages[idx].failed = true
                    }
                    errorMessage = nextErrorLine()
                    ReviewPrompter.shared.noteError()
                    Announce.say(errorMessage)
                    Haptics.play(.failure)
                }
                return nil
            }
        }
        sendTask = t
        return await t.value
    }

    /// One of the error lines, in Sandy's voice with the user's name, never the same twice in a row.
    private func nextErrorLine() -> String {
        let lang = LanguageManager.shared
        let lines = lang.list("chat.sendErrors")
        guard !lines.isEmpty else { return "" }
        var pick = Int.random(in: 0..<lines.count)
        if lines.count > 1 && pick == lastErrorVariant { pick = (pick + 1) % lines.count }
        lastErrorVariant = pick
        let name = userName.isEmpty ? lang.s("chat.friend") : userName
        return String(format: lines[pick], name)
    }

    /// «إيقاف»: the reply stops where it is; what arrived stays, here and in the history.
    func stop(api: APIClient) {
        sendTask?.cancel()
        sendGeneration += 1
        sending = false
        replying = false
        activity = ""
        guard let cid = streamingCid, let cmid = streamingCmid else { return }
        let partial = streamingID.flatMap { id in messages.first { $0.id == id }?.text } ?? ""
        streamingID = nil
        streamingCmid = nil
        if !partial.isEmpty { saveLines(api, id: cid) }
        stopping = true
        Task {
            // Sandy is told it was cut here, and the turn runs no further tool.
            try? await api.stopReply(conversationId: cid, partial: partial, clientMsgId: cmid)
            self.stopping = false
            if !partial.isEmpty { try? await api.appendMessage(cid: cid, role: "sandy", text: partial) }
        }
    }

    /// A failed line, sent again as the same message: last, so the reply follows it, and under
    /// its own id, so a turn the server already ran is answered from its ledger, not run again.
    func retry(api: APIClient, _ message: ChatMessage) async -> String? {
        guard let idx = messages.firstIndex(where: { $0.id == message.id }) else { return nil }
        var line = messages.remove(at: idx)
        line.failed = false
        messages.append(line)
        errorMessage = ""
        return await send(api: api, text: line.text, appendUser: false,
                          resendID: line.clientMsgId ?? Self.newID())
    }

    /// Sandy's last reply, written again: dropped here and on the server, the same line re-answered.
    func regenerate(api: APIClient) async -> String? {
        guard !sending, !stopping, let last = messages.last, last.role == "sandy", let cid = currentID,
              let line = messages.last(where: { $0.role == "user" })?.text else { return nil }
        messages.removeLast()
        errorMessage = ""
        // The old reply's changes (a task it added, a reminder it moved) are taken back.
        guard await rewound(api, cid: cid, keepUser: true) else {
            messages.append(last)
            return nil
        }
        NotificationCenter.default.post(name: .sandyBlocksChanged, object: nil)
        return await send(api: api, text: line, appendUser: false)
    }

    /// The user's last line, edited: it and its reply go, the new line is sent in their place.
    func editLast(api: APIClient, to text: String) async -> String? {
        guard !sending, !stopping, let idx = messages.lastIndex(where: { $0.role == "user" }) else { return nil }
        let kept = messages[idx].attachments   // the edit changes the words, not what came with them
        let dropped = Array(messages[idx...])
        messages.removeSubrange(idx...)
        errorMessage = ""
        if let cid = currentID {
            guard await rewound(api, cid: cid, keepUser: false) else {
                messages.append(contentsOf: dropped)
                return nil
            }
            NotificationCenter.default.post(name: .sandyBlocksChanged, object: nil)
        }
        return await send(api: api, text: text, attachments: kept)
    }

    /// The last reply dropped on the server; false (with the reason shown) when it was not,
    /// so nothing is answered twice. A stopped turn still running holds it back a moment.
    private func rewound(_ api: APIClient, cid: String, keepUser: Bool) async -> Bool {
        do {
            try await api.rewindConversation(id: cid, keepUser: keepUser)
            return true
        } catch {
            if !error.isCancellation {
                errorMessage = (error as? APIError)?.code == "turn_running"
                    ? LanguageManager.shared.s("chat.stillStopping") : nextErrorLine()
                Announce.say(errorMessage)
            }
            return false
        }
    }

    /// كم مرة نعيد إرسال رسالة انقطع اتصالها (مش خطأ من الخادم).
    private static let sendRetries = 2

    /// Re-runs `op` on a connection-level failure only (timeout, dropped
    /// connection, stream cut before `done`) — never on what the server said
    /// (4xx/5xx), never on cancellation — with a short backoff. Safe because
    /// the send carries the same `client_msg_id` each time.
    private func withConnectionRetry<T>(onRetry: () -> Void,
                                        _ op: () async throws -> T) async throws -> T {
        var attempt = 0
        while true {
            do {
                return try await op()
            } catch let e as APIError where e.kind == .connection && attempt < Self.sendRetries {
                attempt += 1
                onRetry()
                try await Task.sleep(nanoseconds: UInt64(attempt) * 500_000_000)
            }
        }
    }

    /// معرّف بصيغة الخادم (uuid hex).
    private static func newID() -> String {
        UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
    }

    /// مقارنة تقريبية (بادئة التاريخ بتوقيت UTC) — تكفي لسلوك "سيشن اليوم".
    private static let iso = ISO8601DateFormatter()

    private func isToday(_ iso: String) -> Bool {
        let today = Self.iso.string(from: Date()).prefix(10)
        return iso.prefix(10) == today
    }
}

/// What a tool's name means on screen while it runs.
@MainActor
enum ChatStep {
    static func label(_ tool: String) -> String {
        let lang = LanguageManager.shared
        let key = "chat.step." + tool
        let text = lang.s(key)
        return text == key ? lang.s("chat.step.other") : text
    }
}

extension Notification.Name {
    /// Sandy changed the blocks from chat (a reply, or a reply taken back): the tabs reload.
    static let sandyBlocksChanged = Notification.Name("sandyBlocksChanged")
}
