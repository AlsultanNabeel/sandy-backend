import SwiftUI

/// يملك المحادثة الحالية + سجل السيشنات. الإرسال يجري في مهمة يملكها الستور
/// (محصّنة ضد إلغاء الإيماءة)، وكل تبادل يُحفظ تلقائيًا بالباك-إند. المرحلة (أ):
/// محادثات متعددة + حفظ + سجل + بحث نصي؛ المرحلة (ب) تضيف التلخيص والاسترجاع.
@MainActor
final class ChatStore: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var sending = false
    @Published var errorMessage = ""
    @Published var conversations: [ConversationMeta] = []
    /// nil = محادثة جديدة "كسولة": معرّفها بيتولّد محليًا مع أول رسالة، والخادم
    /// بينشئها مع أول طلب بيحملها (بلا محادثات فاضية وبلا رحلة إنشاء منفصلة).
    @Published private(set) var currentID: String?

    private var sendTask: Task<String?, Never>?
    /// Bumped per send. A superseded send's cleanup must not clear `sending`
    /// for the send that replaced it.
    private var sendGeneration = 0
    private let currentKey = "sandy_current_conv"

    /// عند فتح التبويب: يحمّل السجل، ويستكمل آخر محادثة من اليوم أو يبدأ نظيفة.
    func bootstrap(api: APIClient) async {
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
        if let list = try? await api.listConversations() { conversations = list }
    }

    func open(api: APIClient, id: String) async {
        // A reply still streaming belongs to the conversation being left.
        sendTask?.cancel()
        if let r = try? await api.getConversation(id: id) {
            messages = r.messages
            errorMessage = ""
            currentID = id
            UserDefaults.standard.set(id, forKey: currentKey)
        }
    }

    /// محادثة جديدة فورية (كسولة): يصفّي العرض، والإنشاء الفعلي عند أول رسالة.
    func startNew() {
        sendTask?.cancel()
        messages = []
        errorMessage = ""
        currentID = nil
        UserDefaults.standard.removeObject(forKey: currentKey)
    }

    func delete(api: APIClient, id: String) async {
        try? await api.deleteConversation(id: id)
        if id == currentID { startNew() }
        await loadList(api: api)
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

    /// يرسل، يخزّن السؤال والرد، ويرجّع رد ساندي (ليقرأه الـView بالصوت).
    func send(api: APIClient, text: String) async -> String? {
        sendTask?.cancel()
        sendGeneration += 1
        let generation = sendGeneration
        messages.append(ChatMessage(role: "user", text: text))
        sending = true
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
        // مفتاح الرسالة: نفسه بكل محاولة، فالخادم ما بيشغّل الدور مرتين.
        let clientMsgID = Self.newID()
        let t = Task { @MainActor () -> String? in
            defer { if generation == sendGeneration { sending = false } }
            // حفظ رسالة المستخدم وتشغيل ساندي مستقلّان — /api/agent بياخد نص
            // الرسالة من الطلب نفسه، مش من القاعدة، فما داعي ننتظر الحفظ. مهمة
            // منفصلة: الرسالة بتنحفظ حتى لو الإرسال اتلغى أو فشل.
            let saveUser = Task { try? await api.appendMessage(cid: cid, role: "user", text: text) }
            // By id, not index: `messages` can be replaced mid-stream (new
            // chat, another conversation opened), and a stored index then
            // points past the end — a crash on the next chunk.
            var sandyID: UUID?
            // أطول نص وصل بأي محاولة — لو فشلت كل المحاولات بنحتفظ فيه بدل ما نمسحه.
            var bestPartial = ""
            do {
                let reply: String
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
                                                           clientMsgId: clientMsgID) { [weak self] partial in
                            guard let self, !Task.isCancelled else { return }
                            if partial.count > bestPartial.count { bestPartial = partial }
                            if let id = sandyID, let idx = self.messages.firstIndex(where: { $0.id == id }) {
                                self.messages[idx].text = partial
                            } else if sandyID == nil {
                                self.sending = false
                                let bubble = ChatMessage(role: "sandy", text: partial)
                                sandyID = bubble.id
                                self.messages.append(bubble)
                            }
                        }
                    }
                    reply = result.reply
                } catch let e as APIError where e.kind == .connection && !bestPartial.isEmpty {
                    // كل المحاولات انقطعت بس وصل جزء من الرد: نحتفظ فيه.
                    reply = bestPartial
                }
                try Task.checkCancellation()
                if let id = sandyID, let idx = messages.firstIndex(where: { $0.id == id }) {
                    messages[idx].text = reply
                } else if sandyID == nil {
                    messages.append(ChatMessage(role: "sandy", text: reply))
                }
                // حفظ الرد وتحديث القائمة بالخلفية — الرد ظاهر، وصوت ساندي ما
                // بيستنّاهم. بالترتيب: رسالة المستخدم قبل الرد (منها العنوان).
                Task {
                    _ = await saveUser.value
                    try? await api.appendMessage(cid: cid, role: "sandy", text: reply)
                    await self.loadList(api: api)
                }
                return reply
            } catch {
                if !error.isCancellation {
                    errorMessage = LanguageManager.shared.s("chat.sendError")
                    Haptics.play(.failure)
                }
                return nil
            }
        }
        sendTask = t
        return await t.value
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
