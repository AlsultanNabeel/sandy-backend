import SwiftUI

@MainActor
final class FutureMessagesStore: LoadableStore {
    /// أي تغيير على القائمة يعيد جدولة إشعارات التسليم المحلية تلقائيًا.
    @Published var messages: [FutureMessage] = [] {
        didSet { scheduleNotifications() }
    }

    private var loadTask: Task<Void, Never>?

    /// إشعار محلي لكل رسالة مستقبلية بموعد تسليم مستقبلي — ساندي «تسلّمها» إلك
    /// بوقتها حتى لو التطبيق مسكّر. عنوان حسب لغة الجهاز، والنص نص الرسالة.
    private func scheduleNotifications() {
        let isAR = Locale.current.language.languageCode?.identifier == "ar"
        let title = isAR ? "رسالة من ساندي" : "A message from Sandy"
        let items = messages.compactMap { m -> NotificationItem? in
            guard let date = NotificationManager.parseISO(m.deliverAt) else { return nil }
            return NotificationItem(id: m.id, title: title, body: m.text, date: date)
        }
        NotificationManager.shared.sync(prefix: "future.", items: items)
    }

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                messages = try await api.futureMessagesList()
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("futureMessages.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// جدولة رسالة جديدة ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, text: String, deliverAt: Date) async -> Bool {
        do {
            let iso = ISO8601DateFormatter().string(from: deliverAt)
            try await api.futureMessagesCreate(text: text, deliverAt: iso)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("futureMessages.errorAdd")
            return false
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, message: FutureMessage) {
        guard let idx = messages.firstIndex(where: { $0.id == message.id }) else { return }
        messages.remove(at: idx)
        Task { @MainActor in
            do {
                try await api.futureMessagesDelete(id: message.id)
            } catch {
                messages.insert(message, at: min(idx, messages.count))
                notice = LanguageManager.shared.s("futureMessages.errorDelete")
            }
        }
    }
}
