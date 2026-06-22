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
    @State private var reminders: [ReminderItem] = []
    @State private var loading = false
    @State private var notice = ""          // رسالة ساندي عند فشل التحميل (فاضي = ما في)
    @State private var demo = false
    @State private var showAdd = false

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if demo { DemoBanner() }

                // خطأ تحميل القائمة — بصوت ساندي مو سطر أحمر.
                if !notice.isEmpty {
                    SandyNotice(notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                content
            }

            // زر الإضافة الجميل — عائم بالأسفل، نص + أيقونة (مو "+").
            if !demo {
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
        .sheet(isPresented: $showAdd) {
            AddReminderSheet { text, remindAt, note in
                try await state.api.addReminder(text: text, remindAt: remindAt, note: note)
                await load()
            }
        }
        .task { await load() }
        .refreshable { await load() }
        .animation(.spring(response: 0.45, dampingFraction: 0.82), value: reminders.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: notice)
    }

    // ── المحتوى: تحميل / فاضي / قائمة ──────────────────────────────────────
    @ViewBuilder
    private var content: some View {
        if loading && reminders.isEmpty {
            Spacer()
            ProgressView()
                .tint(Theme.Colors.accent)
            Spacer()
        } else if reminders.isEmpty {
            Spacer()
            emptyState
            Spacer()
        } else {
            ScrollView {
                VStack(spacing: Theme.Spacing.sm) {
                    ForEach(reminders) { reminder in
                        reminderRow(reminder)
                            .transition(.asymmetric(
                                insertion: .move(edge: .top).combined(with: .opacity),
                                removal: .scale(scale: 0.92).combined(with: .opacity)))
                    }
                }
                .padding(Theme.Spacing.md)
                // مساحة تحت حتى ما يغطّي الزرّ العائم آخر صف.
                .padding(.bottom, Theme.Spacing.xxl + Theme.Spacing.xl)
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
                    .font(.title3)
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
                                .font(.system(size: 11))
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

                VStack(alignment: .trailing, spacing: Theme.Spacing.sm) {
                    if reminder.isRecurring {
                        Text(lang.s("reminders.recurring"))
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.accent)
                            .padding(.vertical, Theme.Spacing.xs)
                            .padding(.horizontal, Theme.Spacing.sm)
                            .background(Theme.Colors.accent.opacity(0.12))
                            .clipShape(Capsule())
                    }
                    if !demo {
                        Button {
                            delete(reminder)
                        } label: {
                            Image(systemName: "trash")
                                .font(.system(size: 15))
                                .foregroundColor(Theme.Colors.danger)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    /// حذف تذكير — تفاؤليًا من القائمة ثم نطلب من السيرفر.
    private func delete(_ reminder: ReminderItem) {
        withAnimation { reminders.removeAll { $0.id == reminder.id } }
        Task {
            do {
                try await state.api.deleteReminder(id: reminder.id)
            } catch {
                notice = lang.s("reminders.loadFailed")
                await load()
            }
        }
    }

    private func load() async {
        loading = true
        notice = ""
        do {
            let r = try await state.api.getReminders()
            reminders = r.items
            demo = r.demo
        } catch {
            // خطأ تحميل — بصوت ساندي ودّي (مو localizedDescription جاف لوحده).
            notice = lang.s("reminders.loadFailed")
        }
        loading = false
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
// MARK: - شيت إضافة تذكير

/// شيت إضافة تذكير: نص (إلزامي) + وقت (افتراضيًا الآن + دقيقتين) + ملاحظة اختيارية.
/// الوقت يُرسل بصيغة ISO 8601. الأخطاء تظهر بصوت ساندي والشيت يبقى مفتوح.
private struct AddReminderSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    /// يستقبل (النص، الوقت ISO، الملاحظة?) ويرمي عند الفشل.
    let onSave: (String, String, String?) async throws -> Void

    @State private var text = ""
    /// افتراضيًا الآن + دقيقتين — حتى تذكير التجربة ما يطلع بالماضي
    /// فيتجنّب رفض الباك-إند لـ "تاريخ بالماضي".
    @State private var date = Date().addingTimeInterval(120)
    @State private var note = ""
    @State private var saving = false
    @State private var notice = ""          // رسالة ساندي عند فشل الحفظ (فاضي = ما في)

    private var trimmedText: String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    private var trimmedNote: String {
        note.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
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
                    SandyButton(title: lang.s("reminders.submit"),
                                systemImage: "checkmark.circle.fill",
                                isLoading: saving,
                                fillWidth: true) {
                        save()
                    }
                    .disabled(trimmedText.isEmpty)
                    .opacity(trimmedText.isEmpty ? 0.6 : 1)
                }
                .padding(Theme.Spacing.lg)
            }
            .background(SandyBackground())
            .navigationTitle(lang.s("reminders.sheetTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("common.cancel")) { dismiss() }
                }
            }
            .animation(.easeInOut(duration: 0.25), value: notice)
        }
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
