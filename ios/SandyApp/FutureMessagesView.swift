import SwiftUI

/// شاشة "رسالة لنفسك المستقبلي" — تكتب كلمة الآن مع موعد مستقبلي، وساندي تحفظها
/// وترجّعها إلك يوم موعدها. تعرض الرسائل القادمة مرتّبة بالأقرب موعداً، مع حذف عبر
/// السحب وقائمة السياق. نمط الستور المعتمد: الجلب بمهمة يملكها الستور.
/// تتكلّم مع `/api/future-messages` (إنشاء/قائمة/حذف).
struct FutureMessagesView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = FutureMessagesStore()
    @State private var showCompose = false

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                content
            }
        }
        .navigationTitle(lang.s("daily.future"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                SandyButton(title: lang.s("futureMessages.add"),
                            systemImage: "plus.circle.fill",
                            style: .secondary) {
                    store.notice = ""
                    showCompose = true
                }
            }
        }
        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.messages.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .fullScreenCover(isPresented: $showCompose) {
            FutureMessageSheet { text, deliverAt in
                await store.add(api: state.api, text: text, deliverAt: deliverAt)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if store.messages.isEmpty && !store.loading {
            emptyView
        } else {
            List {
                header
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: Theme.Spacing.sm, leading: Theme.Spacing.md,
                                              bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                ForEach(store.messages) { msg in
                    messageCard(msg)
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                  bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            Button(role: .destructive) {
                                store.delete(api: state.api, message: msg)
                            } label: { Label(lang.s("futureMessages.delete"), systemImage: "trash") }
                        }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
    }

    private var header: some View {
        Text(lang.s("futureMessages.intro"))
            .font(Theme.Typography.subheadline)
            .foregroundColor(Theme.Colors.secondaryText)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func messageCard(_ msg: FutureMessage) -> some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                HStack(alignment: .top, spacing: Theme.Spacing.md) {
                    Image(systemName: "envelope.fill")
                        .font(.caption)
                        .foregroundColor(Theme.Colors.accent)
                        .padding(.top, 3)
                    Text(msg.text)
                        .font(Theme.Typography.body)
                        .foregroundColor(Theme.Colors.primaryText)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if let label = msg.deliverLabel {
                    Label(label, systemImage: "clock")
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
            }
        }
        .contentShape(Rectangle())
        .contextMenu {
            Button(role: .destructive) {
                store.delete(api: state.api, message: msg)
            } label: { Label(lang.s("futureMessages.delete"), systemImage: "trash") }
        }
    }

    private var emptyView: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "paperplane.fill")
                .font(.system(size: 44))
                .foregroundColor(Theme.Colors.accent.opacity(0.5))
            Text(lang.s("futureMessages.empty"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
            SandyButton(title: lang.s("futureMessages.add"),
                        systemImage: "plus.circle.fill") {
                store.notice = ""
                showCompose = true
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Theme.Spacing.lg)
    }
}

// MARK: - ورقة كتابة رسالة (نص + موعد مستقبلي)

/// ورقة بسيطة: محرّر نص + منتقي تاريخ/وقت لموعد التسليم. تُرسل عبر closure غير
/// متزامن يرجّع نجاح/فشل لتقرّر الورقة إذا بتتقفل. الموعد افتراضياً بعد سنة من الآن.
private struct FutureMessageSheet: View {
    let onSubmit: (_ text: String, _ deliverAt: Date) async -> Bool

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var text = ""
    @State private var deliverAt = Calendar.current.date(byAdding: .year, value: 1, to: Date()) ?? Date()
    @State private var submitting = false
    @State private var notice = ""

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        SandyPopup(title: lang.s("futureMessages.addTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                fieldCard(title: lang.s("futureMessages.sheet.textPrompt")) {
                    TextField(lang.s("futureMessages.sheet.placeholder"), text: $text, axis: .vertical)
                        .font(Theme.Typography.body)
                        .lineLimit(3...8)
                }

                fieldCard(title: lang.s("futureMessages.sheet.timePrompt")) {
                    DatePicker("",
                               selection: $deliverAt,
                               in: Date()...,
                               displayedComponents: [.date, .hourAndMinute])
                        .labelsHidden()
                        .datePickerStyle(.compact)
                        .environment(\.locale, Locale(identifier: "ar"))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                if !notice.isEmpty {
                    SandyNotice(notice, kind: .gentleWarning)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }

                SandyButton(title: lang.s("futureMessages.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
                .disabled(trimmed.isEmpty)
                .opacity(trimmed.isEmpty ? 0.5 : 1)
            }
            .animation(.easeInOut(duration: 0.25), value: notice)
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    /// بطاقة حقل صغيرة بعنوان فوقها — توحّد شكل الحقول.
    @ViewBuilder
    private func fieldCard<Content: View>(title: String,
                                          @ViewBuilder content: @escaping () -> Content) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Text(title)
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.secondaryText)
            SandyCard { content() }
        }
    }

    private func save() {
        guard !trimmed.isEmpty, !submitting else { return }
        // نحرس محليًا: لازم يكون الموعد بالمستقبل — هاي رسالة لبكرة مش لليوم.
        if deliverAt <= Date() {
            notice = lang.s("futureMessages.pastGuard")
            return
        }
        submitting = true
        notice = ""
        Task {
            let ok = await onSubmit(trimmed, deliverAt)
            submitting = false
            if ok { dismiss() } else { notice = lang.s("futureMessages.errorAdd") }
        }
    }
}

// MARK: - النموذج

/// رسالة مجدولة لنفسك المستقبلي — تطابق `/api/future-messages`.
struct FutureMessage: Identifiable {
    let id: String
    let text: String
    let deliverAt: String   // ISO

    /// تسمية موعد لطيفة (مطلقة بالعربية) — أو nil لو الموعد ما انفهم.
    var deliverLabel: String? {
        guard let date = FutureMessage.parseISO(deliverAt) else { return nil }
        let prefix = LanguageManager.shared.s("futureMessages.deliverPrefix")
        return "\(prefix) \(FutureMessage.absoluteLabel(date))"
    }

    /// مُحلِّل ISO متسامح — الباك-إند قد يرسل بمنطقة زمنية أو بدونها.
    static func parseISO(_ s: String) -> Date? {
        if s.isEmpty { return nil }
        let isoFull = ISO8601DateFormatter()
        isoFull.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = isoFull.date(from: s) { return d }
        let isoPlain = ISO8601DateFormatter()
        isoPlain.formatOptions = [.withInternetDateTime]
        if let d = isoPlain.date(from: s) { return d }
        let noTZ = DateFormatter()
        noTZ.locale = Locale(identifier: "en_US_POSIX")
        noTZ.timeZone = TimeZone.current
        noTZ.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return noTZ.date(from: s)
    }

    /// تسمية مطلقة لطيفة (يوم + ساعة) بالعربية.
    static func absoluteLabel(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "ar")
        f.dateStyle = .medium
        f.timeStyle = .short
        return f.string(from: date)
    }
}

// MARK: - الستور

@MainActor
final class FutureMessagesStore: ObservableObject {
    @Published var messages: [FutureMessage] = []
    @Published var loading = false
    @Published var notice = ""

    private var loadTask: Task<Void, Never>?

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

// MARK: - نداءات الباك-إند (/api/future-messages)

extension APIClient {
    // GET /api/future-messages → {"items":[{id,text,deliver_at,created_at}]}
    func futureMessagesList() async throws -> [FutureMessage] {
        let r = try await request("/api/future-messages")
        return (r["items"] as? [[String: Any]] ?? []).compactMap { row in
            guard let id = row["id"] as? String, !id.isEmpty else { return nil }
            return FutureMessage(id: id,
                                 text: row["text"] as? String ?? "",
                                 deliverAt: row["deliver_at"] as? String ?? "")
        }
    }

    // POST /api/future-messages {text, deliver_at(ISO)} → {"ok":true}
    func futureMessagesCreate(text: String, deliverAt: String) async throws {
        _ = try await request("/api/future-messages", method: "POST",
                              body: ["text": text, "deliver_at": deliverAt])
    }

    // DELETE /api/future-messages/<id>
    func futureMessagesDelete(id: String) async throws {
        _ = try await request("/api/future-messages/\(id)", method: "DELETE")
    }
}
