import SwiftUI

/// شاشة الهدايا الرقمية (ضمن هَب «حياتي») — تعرض الهدايا الصغيرة اللي ساندي
/// جهّزتها (شعر/اقتباس/تحفيز/ابتسامة/نكتة/لغز) لشخص ومناسبة، مع جدولة اختيارية.
/// عبر `/api/gifts`. نمط الستور المعتمد: الجلب بمهمة يملكها الستور. لا تيليجرام —
/// الهدية تُحفَظ وتُعرَض عبر REST فقط (التوصيل القديم عبر تيليجرام أُزيل بالكامل).
struct GiftsView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = GiftsStore()
    @State private var showAdd = false

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
        .navigationTitle(lang.s("life.gifts"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                SandyButton(title: lang.s("gifts.add"),
                            systemImage: "gift.fill",
                            style: .secondary) {
                    store.notice = ""
                    showAdd = true
                }
            }
        }
        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.gifts.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .fullScreenCover(isPresented: $showAdd) {
            GiftSheet(api: state.api) { draft in
                await store.add(api: state.api, draft: draft)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if store.gifts.isEmpty && !store.loading {
            emptyView
        } else {
            List {
                header
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: Theme.Spacing.sm, leading: Theme.Spacing.md,
                                              bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                ForEach(store.gifts) { gift in
                    giftCard(gift)
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                  bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            Button(role: .destructive) {
                                store.delete(api: state.api, gift: gift)
                            } label: { Label(lang.s("gifts.delete"), systemImage: "trash") }
                        }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
    }

    private var header: some View {
        Text(lang.s("gifts.intro"))
            .font(Theme.Typography.subheadline)
            .foregroundColor(Theme.Colors.secondaryText)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func giftCard(_ gift: DigitalGift) -> some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                HStack(spacing: Theme.Spacing.sm) {
                    Image(systemName: gift.kind.icon)
                        .font(.headline)
                        .foregroundColor(Theme.Colors.accent)
                    Text(lang.s(gift.kind.titleKey))
                        .font(.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Spacer(minLength: 0)
                    Text(scheduleLabel(gift))
                        .font(.caption2)
                        .foregroundColor(gift.scheduledAt.isEmpty
                                         ? Theme.Colors.secondaryText
                                         : Theme.Colors.accentDeep)
                }
                // لمين + المناسبة.
                Text("\(gift.recipient) · \(gift.occasion)")
                    .font(.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                if !gift.content.isEmpty {
                    Text(gift.content)
                        .font(Theme.Typography.body)
                        .foregroundColor(Theme.Colors.primaryText)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .contextMenu {
            Button(role: .destructive) {
                store.delete(api: state.api, gift: gift)
            } label: { Label(lang.s("gifts.delete"), systemImage: "trash") }
        }
    }

    /// "مجدولة لـ <تاريخ>" أو "محفوظة" حسب وجود موعد.
    private func scheduleLabel(_ gift: DigitalGift) -> String {
        gift.scheduledAt.isEmpty
            ? lang.s("gifts.saved")
            : String(format: lang.s("gifts.scheduledFor"), gift.scheduledAt)
    }

    private var emptyView: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "gift")
                .font(.system(size: 44))
                .foregroundColor(Theme.Colors.accent.opacity(0.5))
            Text(lang.s("gifts.empty"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
            SandyButton(title: lang.s("gifts.add"),
                        systemImage: "gift.fill") {
                store.notice = ""
                showAdd = true
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Theme.Spacing.lg)
    }
}

// MARK: - أنواع الهدايا

/// نوع الهدية — يطابق enum الباك-إند (gift_tools). كل نوع له أيقونة ومفتاح عنوان.
enum GiftKind: String, CaseIterable, Identifiable {
    case poem, quote, motivation, smile, joke, riddle

    var id: String { rawValue }

    /// مفتاح l10n لعنوان النوع (للعرض فقط — القيمة المُرسَلة هي rawValue الثابتة).
    var titleKey: String { "gifts.kind.\(rawValue)" }

    var icon: String {
        switch self {
        case .poem:       return "text.quote"
        case .quote:      return "quote.bubble.fill"
        case .motivation: return "bolt.heart.fill"
        case .smile:      return "face.smiling.fill"
        case .joke:       return "theatermasks.fill"
        case .riddle:     return "puzzlepiece.fill"
        }
    }
}

// MARK: - مسوّدة الهدية (مدخلات الورقة)

/// قيم الورقة قبل الحفظ — تُمرَّر للستور دفعة وحدة.
struct GiftDraft {
    var kind: GiftKind
    var recipient: String
    var occasion: String
    var content: String
    /// "" = محفوظة بلا موعد؛ غير ذلك = تاريخ ISO (yyyy-MM-dd).
    var scheduledAt: String
}

// MARK: - ورقة هدية جديدة

/// ورقة إضافة هدية: نوع + لمين + مناسبة + جدولة اختيارية + نص (تكتبه بنفسك أو
/// تخلّي ساندي تكتبه عبر `/api/gifts/generate`). تُرسَل عبر closure غير متزامن
/// يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
private struct GiftSheet: View {
    let api: APIClient
    let onSubmit: (_ draft: GiftDraft) async -> Bool

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var kind: GiftKind = .smile
    @State private var recipient = ""
    @State private var occasion = ""
    @State private var content = ""
    @State private var scheduled = false
    @State private var date = Date()
    @State private var submitting = false
    @State private var generating = false
    @State private var error = ""

    /// منسّق التاريخ المُرسَل للباك-إند (yyyy-MM-dd ثابت، مستقل عن لغة الواجهة).
    private static let isoDay: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private var recipientTrimmed: String { recipient.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var occasionTrimmed: String { occasion.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var canSave: Bool { !recipientTrimmed.isEmpty && !occasionTrimmed.isEmpty }

    var body: some View {
        SandyPopup(title: lang.s("gifts.addTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                kindSection
                fieldSection(title: lang.s("gifts.recipientSection"),
                             placeholder: lang.s("gifts.recipientPlaceholder"),
                             text: $recipient)
                fieldSection(title: lang.s("gifts.occasionSection"),
                             placeholder: lang.s("gifts.occasionPlaceholder"),
                             text: $occasion)
                scheduleSection
                contentSection

                if !error.isEmpty {
                    SandyNotice(error, kind: .gentleWarning)
                }
                SandyButton(title: lang.s("gifts.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
                .disabled(!canSave)
                .opacity(canSave ? 0.5 : 1)
                .opacity(canSave ? 1 : 0.5)
            }
            .animation(.easeInOut(duration: 0.25), value: error)
            .animation(.easeInOut(duration: 0.25), value: scheduled)
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private var kindSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            SectionHeader(title: lang.s("gifts.kindSection"))
            SandyCard {
                Picker(lang.s("gifts.kindSection"), selection: $kind) {
                    ForEach(GiftKind.allCases) { k in
                        Text(lang.s(k.titleKey)).tag(k)
                    }
                }
                .pickerStyle(.menu)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private func fieldSection(title: String, placeholder: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            SectionHeader(title: title)
            SandyCard {
                TextField(placeholder, text: text)
                    .font(Theme.Typography.body)
            }
        }
    }

    private var scheduleSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            SectionHeader(title: lang.s("gifts.scheduleSection"))
            SandyCard {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    Toggle(lang.s("gifts.scheduleToggle"), isOn: $scheduled)
                        .tint(Theme.Colors.accent)
                    if scheduled {
                        DatePicker("", selection: $date, in: Date()..., displayedComponents: .date)
                            .datePickerStyle(.compact)
                            .labelsHidden()
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }

    private var contentSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            SectionHeader(title: lang.s("gifts.contentSection"))
            SandyCard {
                TextField(lang.s("gifts.contentPlaceholder"), text: $content, axis: .vertical)
                    .font(Theme.Typography.body)
                    .lineLimit(3...8)
            }
            SandyButton(title: lang.s("gifts.generate"),
                        systemImage: "sparkles",
                        style: .secondary,
                        isLoading: generating,
                        fillWidth: true) {
                generate()
            }
            .disabled(!canSave || generating)
            .opacity((!canSave || generating) ? 0.5 : 1)
        }
    }

    /// يطلب من ساندي تكتب نص الهدية حسب النوع + لمين + المناسبة، ويعبّيه بالحقل.
    private func generate() {
        guard canSave, !generating else { return }
        generating = true
        withAnimation { error = "" }
        Task {
            do {
                let text = try await api.giftsGenerate(
                    kind: kind.rawValue,
                    recipient: recipientTrimmed,
                    occasion: occasionTrimmed)
                if !text.isEmpty { content = text }
            } catch {
                withAnimation { self.error = lang.s("gifts.errorGenerate") }
            }
            generating = false
        }
    }

    private func save() {
        guard canSave, !submitting else { return }
        submitting = true
        withAnimation { error = "" }
        let draft = GiftDraft(
            kind: kind,
            recipient: recipientTrimmed,
            occasion: occasionTrimmed,
            content: content.trimmingCharacters(in: .whitespacesAndNewlines),
            scheduledAt: scheduled ? Self.isoDay.string(from: date) : "")
        Task {
            let ok = await onSubmit(draft)
            submitting = false
            if ok {
                dismiss()
            } else {
                withAnimation { error = lang.s("gifts.errorAdd") }
            }
        }
    }
}

// MARK: - الستور

@MainActor
final class GiftsStore: ObservableObject {
    @Published var gifts: [DigitalGift] = []
    @Published var loading = false
    @Published var notice = ""

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                gifts = try await api.getGifts()
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("gifts.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة هدية ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, draft: GiftDraft) async -> Bool {
        do {
            try await api.addGift(kind: draft.kind.rawValue,
                                  recipient: draft.recipient,
                                  occasion: draft.occasion,
                                  content: draft.content,
                                  scheduledAt: draft.scheduledAt)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("gifts.errorAdd")
            return false
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, gift: DigitalGift) {
        guard let idx = gifts.firstIndex(where: { $0.id == gift.id }) else { return }
        gifts.remove(at: idx)
        Task { @MainActor in
            do {
                try await api.deleteGift(id: gift.id)
            } catch {
                gifts.insert(gift, at: min(idx, gifts.count))
                notice = LanguageManager.shared.s("gifts.errorDelete")
            }
        }
    }
}

// MARK: - النموذج

/// هدية رقمية محفوظة (`sandy_gifts`). `DigitalGift` تفاديًا لأي تعارض أسماء.
struct DigitalGift: Identifiable {
    let id: String
    let kind: GiftKind
    let recipient: String
    let occasion: String
    let content: String
    /// "" = محفوظة بلا موعد؛ غير ذلك = تاريخ مجدول (yyyy-MM-dd).
    let scheduledAt: String
}

// MARK: - نداءات الباك-إند (تخصّ الهدايا فقط)

extension APIClient {
    // GET /api/gifts → {"items":[{id,kind,recipient,occasion,content,scheduled_at}]}
    func getGifts() async throws -> [DigitalGift] {
        let r = try await request("/api/gifts")
        return (r["items"] as? [[String: Any]] ?? []).compactMap { row in
            guard let id = row["id"] as? String, !id.isEmpty else { return nil }
            let kind = GiftKind(rawValue: row["kind"] as? String ?? "smile") ?? .smile
            return DigitalGift(id: id,
                               kind: kind,
                               recipient: row["recipient"] as? String ?? "",
                               occasion: row["occasion"] as? String ?? "",
                               content: row["content"] as? String ?? "",
                               scheduledAt: row["scheduled_at"] as? String ?? "")
        }
    }

    // POST /api/gifts {kind,recipient,occasion,content,scheduled_at} → {"ok","id"}
    func addGift(kind: String, recipient: String, occasion: String,
                 content: String, scheduledAt: String) async throws {
        _ = try await request("/api/gifts", method: "POST", body: [
            "kind": kind,
            "recipient": recipient,
            "occasion": occasion,
            "content": content,
            "scheduled_at": scheduledAt,
        ])
    }

    // POST /api/gifts/generate {kind,recipient,occasion} → {"content"} — توليد نص (بلا حفظ).
    func giftsGenerate(kind: String, recipient: String, occasion: String) async throws -> String {
        let r = try await request("/api/gifts/generate", method: "POST", body: [
            "kind": kind, "recipient": recipient, "occasion": occasion,
        ])
        return r["content"] as? String ?? ""
    }

    // DELETE /api/gifts/<id>
    func deleteGift(id: String) async throws {
        _ = try await request("/api/gifts/\(id)", method: "DELETE")
    }
}
