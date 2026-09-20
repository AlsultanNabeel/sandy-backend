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
    /// nil = محادثة جديدة "كسولة": تُنشأ بالباك-إند فقط عند أول رسالة (بلا محادثات فاضية).
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
        let t = Task { @MainActor () -> String? in
            defer { if generation == sendGeneration { sending = false } }
            do {
                if currentID == nil {
                    let id = try await api.createConversation()
                    currentID = id
                    UserDefaults.standard.set(id, forKey: currentKey)
                }
                let cid = currentID ?? ""
                // حفظ رسالة المستخدم وتشغيل ساندي مستقلّان — /api/agent بياخد نص
                // الرسالة من الطلب نفسه، مش من القاعدة، فما داعي ننتظر الحفظ.
                async let saveUser: () = api.appendMessage(cid: cid, role: "user", text: text)
                // نمرّر سيشن المحادثة فتتذكّرها ساندي مستقلة عن باقي محادثاتك. أول
                // قطعة توصل تستبدل مؤشّر الكتابة بفقاعة نصّية تكبر تدريجياً — ردود
                // الأدوات (زي "أضف مهمة") ما فيها قطع، بترجع دفعة وحدة بالنهاية.
                // By id, not index: `messages` can be replaced mid-stream (new
                // chat, another conversation opened), and a stored index then
                // points past the end — a crash on the next chunk.
                var sandyID: UUID?
                let (reply, _) = try await api.sendMessageStreaming(text, conversationId: cid) { [weak self] partial in
                    guard let self, !Task.isCancelled else { return }
                    if let id = sandyID, let idx = self.messages.firstIndex(where: { $0.id == id }) {
                        self.messages[idx].text = partial
                    } else if sandyID == nil {
                        self.sending = false
                        let bubble = ChatMessage(role: "sandy", text: partial)
                        sandyID = bubble.id
                        self.messages.append(bubble)
                    }
                }
                _ = try? await saveUser
                try Task.checkCancellation()
                if let id = sandyID, let idx = messages.firstIndex(where: { $0.id == id }) {
                    messages[idx].text = reply
                } else if sandyID == nil {
                    messages.append(ChatMessage(role: "sandy", text: reply))
                }
                try? await api.appendMessage(cid: cid, role: "sandy", text: reply)
                // تحديث قائمة المحادثات لا يوقف ظهور الردّ — يشتغل بالخلفية.
                Task { await loadList(api: api) }
                return reply
            } catch {
                if !error.isCancellation { errorMessage = LanguageManager.shared.s("chat.sendError") }
                return nil
            }
        }
        sendTask = t
        return await t.value
    }

    /// مقارنة تقريبية (بادئة التاريخ بتوقيت UTC) — تكفي لسلوك "سيشن اليوم".
    private static let iso = ISO8601DateFormatter()

    private func isToday(_ iso: String) -> Bool {
        let today = Self.iso.string(from: Date()).prefix(10)
        return iso.prefix(10) == today
    }
}
