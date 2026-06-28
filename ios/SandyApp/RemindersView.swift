import SwiftUI

/// تبويب تذكيراتي — يعرض التذكيرات مع إضافة تذكير (نص + وقت + ملاحظة) عبر POST /api/reminders.
///
/// نكهة ساندي:
///   • زر إضافة جميل بنص وأيقونة (مو "+" أصلع).
///   • الشيت يفتح وقته جاهز على "الآن + دقيقتين" حتى ما يصير تذكير بالماضي.
///   • الأخطاء بصوت ساندي عبر SandyNotice (مو سطر أحمر).
///   • حيوية: صفوف تدخل/تخرج بنعومة، حالة فاضية مفعمة، وعرض وقت لطيف (نسبي + مطلق).
struct RemindersView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    /// مصدر الحقيقة للتذكيرات (يملك البيانات + الجلب + التعديلات، مستقل عن الشاشة).
    @StateObject private var store = RemindersStore()
    @State private var showAdd = false
    /// التذكير الجاري تعديله (nil = ما في ورقة تعديل مفتوحة).
    @State private var editingReminder: ReminderItem?

    var body: some View {
        // الخلفية موحّدة على مستوى MainTabView — لا نكرّرها هون (طبقة مهدورة).
        ZStack {
            VStack(spacing: 0) {
                if store.demo { DemoBanner() }

                // خطأ تحميل القائمة — بصوت ساندي مو سطر أحمر.
                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                content
            }

            // زر الإضافة الجميل — عائم بالأسفل، نص + أيقونة (مو "+").
            if !store.demo {
                VStack {
                    Spacer()
                    SandyButton(title: lang.s("reminders.add"),
                                systemImage: "bell.badge.fill",
                                fillWidth: true) {
                        showAdd = true
                    }
                    .padding(.horizontal, Theme.Spacing.lg)
                    .padding(.bottom, Theme.Spacing.lg)
                }
            }
        }
        .navigationTitle(lang.s("reminders.title"))
        .fullScreenCover(isPresented: $showAdd) {
            ReminderSheet { text, remindAt, note in
                try await store.add(api: state.api, text: text, remindAt: remindAt, note: note)
            }
        }
        .fullScreenCover(item: $editingReminder) { reminder in
            ReminderSheet(existing: reminder) { text, remindAt, note in
                try await store.update(api: state.api, id: reminder.id,
                                       text: text, remindAt: remindAt, note: note)
            }
        }
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .animation(.spring(response: 0.45, dampingFraction: 0.82), value: store.reminders.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
    }

    // ── المحتوى: تحميل / فاضي / قائمة ──────────────────────────────────────
    @ViewBuilder
    private var content: some View {
        if store.loading && store.reminders.isEmpty {
            Spacer()
            ProgressView()
                .tint(Theme.Colors.accent)
            Spacer()
        } else if store.reminders.isEmpty {
            Spacer()
            emptyState
            Spacer()
        } else {
            // قائمة أصلية: إيماءات سحب قياسية مع إبقاء بطاقات ساندي (نفس وصفة المهام).
            List {
                ForEach(store.reminders) { reminder in
                    reminderRow(reminder)
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                  bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            if !store.demo {
                                Button(role: .destructive) {
                                    store.delete(api: state.api, reminder: reminder)
                                } label: { Label(lang.s("reminders.delete"), systemImage: "trash") }
                            }
                        }
                        .swipeActions(edge: .leading) {
                            if !store.demo {
                                Button { editingReminder = reminder } label: {
                                    Label(lang.s("reminders.edit"), systemImage: "pencil")
                                }
                                .tint(Theme.Colors.accent)
                            }
                        }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            // مساحة تحت حتى ما يغطّي الزرّ العائم آخر صف.
            .safeAreaInset(edge: .bottom) {
                Color.clear.frame(height: Theme.Spacing.xxl + Theme.Spacing.xl)
            }
        }
    }

    // ── حالة فاضية مفعمة: أفاتار ساندي + جملة مشجّعة ──────────────────────
    private var emptyState: some View {
        VStack(spacing: Theme.Spacing.md) {
            SandyAvatar(size: 72, mood: .happy)
            Text(lang.s("reminders.emptyTitle"))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
            Text(lang.s("reminders.emptyHint"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, Theme.Spacing.xl)
    }

    // ── صف تذكير: أيقونة + نص + ملاحظة + وقت لطيف (نسبي + مطلق) ───────────
    @ViewBuilder
    private func reminderRow(_ reminder: ReminderItem) -> some View {
        SandyCard {
            HStack(alignment: .top, spacing: Theme.Spacing.md) {
                Image(systemName: reminder.isRecurring ? "repeat.circle.fill" : "bell.fill")
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(Theme.Colors.accent)

                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(reminder.text)
                        .font(Theme.Typography.body)
                        .foregroundColor(Theme.Colors.primaryText)
                        .fixedSize(horizontal: false, vertical: true)

                    if !reminder.note.isEmpty {
                        Text(reminder.note)
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    if let parsed = Self.parseISO(reminder.remindAt) {
                        HStack(spacing: Theme.Spacing.xs) {
                            Image(systemName: "clock")
                                .font(.system(size: Theme.Icon.sm, weight: .semibold))
                            Text(Self.relativeLabel(parsed))
                                .fontWeight(.semibold)
                            Text("•")
                            Text(Self.absoluteLabel(parsed))
                        }
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.accentDeep)
                    } else if !reminder.remindAt.isEmpty {
                        // ما قدرنا نحلّل التاريخ — نعرض النص الخام بهدوء.
                        Text(reminder.remindAt)
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                }

                Spacer(minLength: 0)

                if reminder.isRecurring {
                    Text(lang.s("reminders.recurring"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.accent)
                        .padding(.vertical, Theme.Spacing.xs)
                        .padding(.horizontal, Theme.Spacing.sm)
                        .background(Theme.Colors.accent.opacity(0.12))
                        .clipShape(Capsule())
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { if !store.demo { editingReminder = reminder } }
        .contextMenu {
            if !store.demo {
                Button { editingReminder = reminder } label: {
                    Label(lang.s("reminders.edit"), systemImage: "pencil")
                }
                Button(role: .destructive) {
                    store.delete(api: state.api, reminder: reminder)
                } label: { Label(lang.s("reminders.delete"), systemImage: "trash") }
            }
        }
    }

    // ── أدوات تنسيق الوقت (ثابتة، قابلة لإعادة الاستخدام داخل العرض) ──────

    /// مُحلِّل ISO متسامح — الباك-إند أحيانًا يرسل بلا منطقة زمنية.
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
        if let d = noTZ.date(from: s) { return d }
        let dateOnly = DateFormatter()
        dateOnly.locale = Locale(identifier: "en_US_POSIX")
        dateOnly.timeZone = TimeZone.current
        dateOnly.dateFormat = "yyyy-MM-dd"
        return dateOnly.date(from: s)
    }

    /// تسمية نسبية بالعربية ("بعد ساعتين" / "من 3 دقائق").
    static func relativeLabel(_ date: Date) -> String {
        let f = RelativeDateTimeFormatter()
        f.locale = Locale(identifier: "ar")
        f.unitsStyle = .full
        return f.localizedString(for: date, relativeTo: Date())
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

// ─────────────────────────────────────────────────────────────────────────
// MARK: - الستور (مصدر الحقيقة)

/// يملك تذكيرات المستخدم والجلب والتعديلات، مستقل عن دورة حياة الشاشة. الجلب
/// بمهمة مملوكة للستور، فإلغاء إيماءة السحب ما يلغيه — والجديد يبيّن دايماً.
@MainActor
final class RemindersStore: ObservableObject {
    /// أي تغيير على القائمة (جلب/إضافة/تعديل/حذف) يعيد جدولة الإشعارات المحلية.
    @Published var reminders: [ReminderItem] = [] {
        didSet { scheduleNotifications() }
    }
    @Published var loading = false
    @Published var demo = false
    @Published var notice = ""

    private var loadTask: Task<Void, Never>?

    /// نجدول إشعارًا محليًا لكل تذكير إله وقت مستقبلي. عنوان الإشعار حسب لغة
    /// الجهاز (نتجنّب main actor)، ونصّه نص التذكير نفسه. الماضي يُتجاهل تلقائيًا.
    private func scheduleNotifications() {
        let isAR = Locale.current.language.languageCode?.identifier == "ar"
        let title = isAR ? "تذكير" : "Reminder"
        let items = reminders.compactMap { r -> NotificationItem? in
            guard let date = NotificationManager.parseISO(r.remindAt) else { return nil }
            return NotificationItem(id: r.id, title: title, body: r.text, date: date)
        }
        NotificationManager.shared.sync(prefix: "reminder.", items: items)
    }

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                let r = try await api.getReminders()
                reminders = r.items
                demo = r.demo
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("reminders.loadFailed") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة تذكير ثم إعادة جلب — يرمي عند الفشل ليتعامل الشيت معه.
    func add(api: APIClient, text: String, remindAt: String, note: String?) async throws {
        try await api.addReminder(text: text, remindAt: remindAt, note: note)
        await load(api: api)
    }

    /// تعديل تذكير ثم إعادة جلب — يرمي عند الفشل ليتعامل الشيت معه. الملاحظة
    /// تُرسل دايمًا (حتى الفاضية = مسح)، فنمرّر "" مو nil.
    func update(api: APIClient, id: String, text: String, remindAt: String, note: String?) async throws {
        try await api.updateReminder(id: id, text: text, remindAt: remindAt, note: note ?? "")
        await load(api: api)
    }

    /// حذف تفاؤلي ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, reminder: ReminderItem) {
        reminders.removeAll { $0.id == reminder.id }
        Task { @MainActor in
            do {
                try await api.deleteReminder(id: reminder.id)
            } catch {
                notice = LanguageManager.shared.s("reminders.loadFailed")
                await load(api: api)
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// MARK: - شيت إضافة تذكير

/// شيت تذكير (إضافة أو تعديل): نص (إلزامي) + وقت + ملاحظة اختيارية. `existing`
/// غير nil ⇒ وضع تعديل (تعبئة مسبقة). الوقت يُرسل ISO 8601. الأخطاء بصوت ساندي.
struct ReminderSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    /// التذكير القائم عند التعديل (nil = إضافة جديدة).
    let existing: ReminderItem?
    /// يستقبل (النص، الوقت ISO، الملاحظة?) ويرمي عند الفشل.
    let onSave: (String, String, String?) async throws -> Void

    @State private var text: String
    /// افتراضيًا الآن + دقيقتين — حتى تذكير التجربة ما يطلع بالماضي
    /// فيتجنّب رفض الباك-إند لـ "تاريخ بالماضي".
    @State private var date: Date
    @State private var note: String
    @State private var saving = false
    @State private var notice = ""          // رسالة ساندي عند فشل الحفظ (فاضي = ما في)

    init(existing: ReminderItem? = nil,
         onSave: @escaping (String, String, String?) async throws -> Void) {
        self.existing = existing
        self.onSave = onSave
        _text = State(initialValue: existing?.text ?? "")
        _note = State(initialValue: existing?.note ?? "")
        let parsed = existing.flatMap { RemindersView.parseISO($0.remindAt) }
        _date = State(initialValue: parsed ?? Date().addingTimeInterval(120))
    }

    private var isEditing: Bool { existing != nil }

    private var trimmedText: String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    private var trimmedNote: String {
        note.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        SandyPopup(title: lang.s(isEditing ? "reminders.editTitle" : "reminders.sheetTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {

                // ترويسة ودّية بصوت ساندي
                HStack(spacing: Theme.Spacing.sm) {
                    SandyAvatar(size: 36, mood: .happy)
                    Text(lang.s("reminders.sheetHeader"))
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Spacer(minLength: 0)
                }

                // ── نص التذكير (إلزامي) ──
                fieldCard(title: lang.s("reminders.textField")) {
                    TextField(lang.s("reminders.textPlaceholder"), text: $text, axis: .vertical)
                        .font(Theme.Typography.body)
                        .lineLimit(1...4)
                }

                // ── الوقت (افتراضيًا الآن + دقيقتين) ──
                fieldCard(title: lang.s("reminders.timeField")) {
                    DatePicker("",
                               selection: $date,
                               displayedComponents: [.date, .hourAndMinute])
                        .labelsHidden()
                        .datePickerStyle(.compact)
                        .environment(\.locale, Locale(identifier: "ar"))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                // ── ملاحظة اختيارية (متعدّد الأسطر) ──
                fieldCard(title: lang.s("reminders.noteField")) {
                    TextField(lang.s("reminders.notePlaceholder"), text: $note, axis: .vertical)
                        .font(Theme.Typography.body)
                        .lineLimit(1...5)
                }

                // ── خطأ بصوت ساندي (مو سطر أحمر) ──
                if !notice.isEmpty {
                    SandyNotice(notice, kind: .gentleWarning)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }

                // ── زر الحفظ الجميل ──
                SandyButton(title: lang.s(isEditing ? "reminders.saveEdit" : "reminders.submit"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: saving,
                            fillWidth: true) {
                    save()
                }
                .disabled(trimmedText.isEmpty)
                .opacity(trimmedText.isEmpty ? 0.6 : 1)
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
            SandyCard {
                content()
            }
        }
    }

    private func save() {
        let body = trimmedText
        guard !body.isEmpty else { return }
        saving = true
        notice = ""

        // نحرس محليًا قبل ما نرسل: لو الوقت بالماضي نوجّه بلطف بدل ما نتعب الباك-إند.
        if date <= Date() {
            saving = false
            notice = lang.s("reminders.pastGuard")
            return
        }

        let iso = ISO8601DateFormatter().string(from: date)
        let noteToSend: String? = trimmedNote.isEmpty ? nil : trimmedNote

        Task {
            do {
                try await onSave(body, iso, noteToSend)
                dismiss()
            } catch {
                // فشل الحفظ — نبقي الشيت مفتوح ونعتذر بلطف بصوت ساندي.
                let raw = (error as? APIError)?.message ?? error.localizedDescription
                if raw.contains("past") || raw.contains("ماضي") {
                    notice = lang.s("reminders.savePast")
                } else {
                    notice = lang.s("reminders.saveFailed")
                }
                saving = false
            }
        }
    }
}
