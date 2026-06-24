import SwiftUI

/// تبويب مهامي — يعرض المهام من الباك-إند، مع زر إضافة حقيقي يفتح ورقة تفصيلية
/// (عنوان + موعد + أولوية + ملاحظة)، تعليم منجز بنقرة، وحيوية بالحركات.
struct TasksView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    /// مصدر الحقيقة للمهام: يملك البيانات + الجلب + التعديلات، مستقل عن دورة حياة
    /// الشاشة — فالسحب/التنقّل ما يلغي الجلب، والجديد يبيّن دايماً.
    @StateObject private var store = TasksStore()

    @State private var showAddSheet = false
    /// false = النشطة، true = المكتملة.
    @State private var showCompleted = false

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if store.demo { DemoBanner() }

                filterBar

                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                content
            }
        }
        .navigationTitle(lang.s("tasks.title"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                addButton
            }
        }
        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.tasks.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api, completed: showCompleted) }
        .refreshable { await store.load(api: state.api, completed: showCompleted) }
        .sheet(isPresented: $showAddSheet) {
            AddTaskSheet { text, due, note, priority in
                await submit(text: text, due: due, note: note, priority: priority)
            }
        }
    }

    // MARK: - فلتر نشطة/مكتملة

    private var filterBar: some View {
        Picker("", selection: $showCompleted) {
            Text(lang.s("tasks.filterActive")).tag(false)
            Text(lang.s("tasks.filterCompleted")).tag(true)
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, Theme.Spacing.sm)
        .onChange(of: showCompleted) { _ in
            Task { await store.load(api: state.api, completed: showCompleted) }
        }
    }

    // MARK: - المحتوى (تحميل / فاضي / قائمة)

    @ViewBuilder
    private var content: some View {
        if store.loading && store.tasks.isEmpty {
            loadingState
        } else if store.tasks.isEmpty {
            emptyState
        } else {
            ScrollView {
                VStack(spacing: Theme.Spacing.sm) {
                    ForEach(store.tasks) { task in
                        TaskRow(task: task) { store.toggle(api: state.api, task: task) }
                            .transition(
                                .asymmetric(
                                    insertion: .scale(scale: 0.92).combined(with: .opacity),
                                    removal: .opacity.combined(with: .move(edge: .leading))
                                )
                            )
                    }
                }
                .padding(Theme.Spacing.md)
            }
        }
    }

    /// حالة تحميل حيّة — ساندي تنبض بلطف مع سطر مطمئن.
    private var loadingState: some View {
        VStack(spacing: Theme.Spacing.md) {
            Spacer()
            PulsingSandy()
            Text(lang.s("tasks.loadingLine"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    /// حالة فاضية حيّة — أفاتار ساندي + جملة مشجّعة + زر إضافة بارز.
    private var emptyState: some View {
        VStack(spacing: Theme.Spacing.lg) {
            Spacer()
            SandyAvatar(size: 76, mood: .happy)
            VStack(spacing: Theme.Spacing.xs) {
                Text(lang.s("tasks.emptyTitle"))
                    .font(Theme.Typography.title)
                    .foregroundColor(Theme.Colors.primaryText)
                Text(showCompleted ? lang.s("tasks.emptyCompleted") : lang.s("tasks.emptySubtitle"))
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .multilineTextAlignment(.center)
            }
            if !showCompleted {
                SandyButton(title: lang.s("tasks.add"),
                            systemImage: "plus.circle.fill") {
                    store.notice = ""
                    showAddSheet = true
                }
            }
            Spacer()
            Spacer()
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, Theme.Spacing.xl)
    }

    /// زر الإضافة في شريط التنقّل — زر حقيقي بعنوان وأيقونة، مو "+" عارية.
    private var addButton: some View {
        SandyButton(title: lang.s("tasks.add"),
                    systemImage: "plus.circle.fill",
                    style: .secondary) {
            store.notice = ""
            showAddSheet = true
        }
    }

    // MARK: - البيانات

    /// إرسال مهمة جديدة من الورقة. الموعد يُنسّق ISO هون؛ باقي المنطق (إضافة +
    /// إعادة جلب) بالستور. نرجّع Bool: نجاح = نقفل الورقة، فشل = نُبقيها.
    private func submit(text: String,
                        due: Date?,
                        note: String,
                        priority: String) async -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        let dueISO = due.map { Self.iso.string(from: $0) } ?? ""
        let trimmedNote = note.trimmingCharacters(in: .whitespacesAndNewlines)
        return await store.add(api: state.api, text: trimmed, due: dueISO,
                               note: trimmedNote.isEmpty ? nil : trimmedNote, priority: priority)
    }

    // مُنسّق ISO8601 موحّد للموعد المُرسَل للباك-إند.
    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
}

// MARK: - الستور (مصدر الحقيقة)

/// يملك مهام المستخدم والجلب والتعديلات، منفصل عن دورة حياة الشاشة. مفتاح الحل:
/// الجلب بيشتغل بمهمة **مملوكة للستور** (`loadTask`)، فلمّا إيماءة السحب/التنقّل
/// تنتهي وتلغي إطار الواجهة، الجلب بيكمّل ويحدّث `tasks` — والجديد يبيّن دايماً.
/// هاي معمارية "مصدر حقيقة واحد"، نفس نمط التطبيقات الكبيرة.
@MainActor
final class TasksStore: ObservableObject {
    @Published var tasks: [TaskItem] = []
    @Published var loading = false
    @Published var demo = false
    /// رسالة ودّية بصوت ساندي (فاضية = ما في خطأ).
    @Published var notice = ""

    private var loadTask: Task<Void, Never>?

    /// يبدأ جلباً مملوكاً للستور وينتظره — يصلح للـ `.task` و`.refreshable` معاً.
    /// لو انلغى انتظار الواجهة، المهمة المملوكة بتكمّل وبتحدّث الحالة.
    func load(api: APIClient, completed: Bool) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                let r = try await api.getTasks(completed: completed)
                tasks = r.items
                demo = r.demo
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("tasks.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة مهمة ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, text: String, due: String, note: String?, priority: String) async -> Bool {
        do {
            try await api.addTask(text: text, due: due, note: note, priority: priority)
            notice = ""
            await load(api: api, completed: false)
            return true
        } catch {
            notice = LanguageManager.shared.s("tasks.errorAdd")
            return false
        }
    }

    /// تبديل الإنجاز بتحديث متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func toggle(api: APIClient, task: TaskItem) {
        guard let idx = tasks.firstIndex(where: { $0.id == task.id }) else { return }
        let target = !task.done
        tasks[idx].done = target
        Task { @MainActor in
            do {
                try await api.setTaskDone(id: task.id, done: target)
            } catch {
                if let i = tasks.firstIndex(where: { $0.id == task.id }) { tasks[i].done = !target }
                notice = LanguageManager.shared.s("tasks.errorToggle")
            }
        }
    }
}

// MARK: - صف المهمة

/// صف مهمة واحد: زر تعليم بنقرة (مع حركة check مُرضية)، النص، الأولوية، الموعد.
private struct TaskRow: View {
    let task: TaskItem
    let onToggle: () -> Void

    var body: some View {
        SandyCard {
            HStack(alignment: .top, spacing: Theme.Spacing.md) {
                Button(action: onToggle) {
                    Image(systemName: task.done ? "checkmark.circle.fill" : "circle")
                        .font(.title3)
                        .foregroundColor(task.done ? Theme.Colors.success : Theme.Colors.secondaryText)
                        // حركة check مُرضية: تكبر لحظة عند الإنجاز.
                        .scaleEffect(task.done ? 1.18 : 1.0)
                        .animation(.spring(response: 0.3, dampingFraction: 0.45), value: task.done)
                }
                .buttonStyle(.plain)

                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(task.text)
                        .font(Theme.Typography.body)
                        .strikethrough(task.done, color: Theme.Colors.secondaryText)
                        .foregroundColor(task.done ? Theme.Colors.secondaryText : Theme.Colors.primaryText)

                    if !task.note.isEmpty {
                        Text(task.note)
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                            .lineLimit(2)
                    }

                    HStack(spacing: Theme.Spacing.sm) {
                        PriorityBadge(priority: task.priority)
                        if let dueText = Self.format(task.dueAt) {
                            Label(dueText, systemImage: "calendar")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.secondaryText)
                        }
                    }
                }

                Spacer(minLength: 0)
            }
        }
        .opacity(task.done ? 0.7 : 1.0)
    }

    /// تنسيق الموعد القادم من الباك-إند (ISO أو بدون منطقة) لعرض عربي لطيف.
    private static func format(_ iso: String) -> String? {
        guard !iso.isEmpty else { return nil }
        let parsers: [ISO8601DateFormatter] = {
            let full = ISO8601DateFormatter()
            full.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let plain = ISO8601DateFormatter()
            plain.formatOptions = [.withInternetDateTime]
            return [full, plain]
        }()
        var date: Date?
        for p in parsers where date == nil { date = p.date(from: iso) }
        if date == nil {
            let df = DateFormatter()
            df.locale = Locale(identifier: "en_US_POSIX")
            df.timeZone = TimeZone.current
            df.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            date = df.date(from: iso)
        }
        guard let d = date else { return nil }
        let out = DateFormatter()
        out.locale = Locale(identifier: "ar")
        out.dateStyle = .medium
        out.timeStyle = .short
        return out.string(from: d)
    }
}

// MARK: - شارة الأولوية

/// شارة أولوية ملوّنة: عالية (تنبيه)، عادية (مرجاني)، منخفضة (نجاح).
private struct PriorityBadge: View {
    @EnvironmentObject var lang: LanguageManager
    let priority: String

    var body: some View {
        HStack(spacing: Theme.Spacing.xs) {
            Circle()
                .fill(color)
                .frame(width: 8, height: 8)
            Text(label)
                .font(Theme.Typography.caption)
                .foregroundColor(color)
        }
        .padding(.vertical, 3)
        .padding(.horizontal, Theme.Spacing.sm)
        .background(color.opacity(0.12))
        .clipShape(Capsule())
    }

    private var color: Color {
        switch priority {
        case "high": return Theme.Colors.warn
        case "low":  return Theme.Colors.success
        default:     return Theme.Colors.accent
        }
    }
    // التسمية المرئية فقط — القيمة الخام ("high"/"low"/"normal") تبقى للباك-إند.
    private var label: String {
        switch priority {
        case "high": return lang.s("tasks.priorityHigh")
        case "low":  return lang.s("tasks.priorityLow")
        default:     return lang.s("tasks.priorityNormal")
        }
    }
}

// MARK: - ساندي نابضة (حالة التحميل)

/// أفاتار ساندي ينبض بلطف — يخلّي التحميل يحسّ حيّ مو ProgressView جامد.
private struct PulsingSandy: View {
    @State private var pulse = false
    var body: some View {
        SandyAvatar(size: 64, mood: .happy)
            .scaleEffect(pulse ? 1.08 : 0.94)
            .opacity(pulse ? 1.0 : 0.8)
            .onAppear {
                withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) {
                    pulse = true
                }
            }
    }
}

// MARK: - ورقة إضافة مهمة (تفصيلية)

/// ورقة الإضافة: عنوان (إلزامي) + موعد اختياري (تاريخ ووقت) + أولوية (شرائح)
/// + ملاحظة اختيارية (متعدّد أسطر). تُرسل عبر closure غير متزامن يرجّع نجاح/فشل.
private struct AddTaskSheet: View {
    /// closure الإرسال: يرجّع true عند النجاح حتى نقفل الورقة.
    let onSubmit: (_ text: String, _ due: Date?, _ note: String, _ priority: String) async -> Bool

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var text = ""
    @State private var hasDue = false
    @State private var due = Date().addingTimeInterval(3600)
    @State private var priority = "normal"
    @State private var note = ""
    @State private var submitting = false

    private var canSave: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        NavigationView {
            ZStack {
                SandyBackground()

                ScrollView {
                    VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                        titleSection
                        prioritySection
                        dueSection
                        noteSection

                        SandyButton(title: lang.s("tasks.saveTask"),
                                    systemImage: "checkmark.circle.fill",
                                    isLoading: submitting,
                                    fillWidth: true) {
                            save()
                        }
                        .disabled(!canSave)
                        .opacity(canSave ? 1 : 0.5)
                    }
                    .padding(Theme.Spacing.md)
                }
            }
            .navigationTitle(lang.s("tasks.newTask"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button(lang.s("common.cancel")) { dismiss() }
                        .foregroundColor(Theme.Colors.accentDeep)
                }
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    // ── العنوان (إلزامي) ──
    private var titleSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            SectionHeader(title: lang.s("tasks.titleQuestion"))
            SandyCard {
                TextField(lang.s("tasks.titlePlaceholder"), text: $text, axis: .vertical)
                    .font(Theme.Typography.body)
                    .lineLimit(1...3)
            }
        }
    }

    // ── الأولوية (شرائح) ──
    private var prioritySection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            SectionHeader(title: lang.s("tasks.priority"))
            // القيم الخام في .tag تبقى للباك-إند؛ التسميات المرئية فقط تُترجم.
            Picker(lang.s("tasks.priority"), selection: $priority) {
                Text(lang.s("tasks.priorityLow")).tag("low")
                Text(lang.s("tasks.priorityNormal")).tag("normal")
                Text(lang.s("tasks.priorityHigh")).tag("high")
            }
            .pickerStyle(.segmented)
        }
    }

    // ── الموعد (اختياري: تاريخ + وقت) ──
    private var dueSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Toggle(isOn: $hasDue.animation(.easeInOut(duration: 0.2))) {
                Text(lang.s("tasks.dueToggle"))
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
            }
            .tint(Theme.Colors.accent)

            if hasDue {
                SandyCard {
                    DatePicker(lang.s("tasks.dueDate"),
                               selection: $due,
                               displayedComponents: [.date, .hourAndMinute])
                        .datePickerStyle(.compact)
                        .environment(\.locale, Locale(identifier: "ar"))
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }

    // ── الملاحظة (اختياري، متعدّد أسطر) ──
    private var noteSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            SectionHeader(title: lang.s("tasks.noteHeader"))
            SandyCard {
                TextField(lang.s("tasks.notePlaceholder"), text: $note, axis: .vertical)
                    .font(Theme.Typography.body)
                    .lineLimit(3...6)
            }
        }
    }

    private func save() {
        guard canSave, !submitting else { return }
        submitting = true
        let dueValue: Date? = hasDue ? due : nil
        Task {
            let ok = await onSubmit(text, dueValue, note, priority)
            submitting = false
            if ok { dismiss() }
        }
    }
}
