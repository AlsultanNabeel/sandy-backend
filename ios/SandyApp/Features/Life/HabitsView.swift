import SwiftUI

/// شاشة العادات — تعرض العادات مع إضافة (بشيت ألطف) وتسجيل حضور اليوم مع احتفال بالسلسلة.
struct HabitsView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    /// مصدر الحقيقة للعادات (يملك البيانات + الجلب + التعديلات، مستقل عن الشاشة).
    @StateObject private var store = HabitsStore()
    @State private var showAdd = false
    /// العادة الجاري تعديلها (nil = ما في ورقة تعديل مفتوحة).
    @State private var editingHabit: HabitItem?
    /// آيدي العادة التي سُجّل حضورها للتو — يشغّل أنميشن الاحتفال بالسلسلة.
    @State private var celebratingID: String? = nil

    var body: some View {
        // الخلفية موحّدة على مستوى MainTabView — لا نكرّرها هون (طبقة مهدورة).
        ZStack {
            VStack(spacing: 0) {
                if store.demo { DemoBanner() }

                if !store.error.isEmpty {
                    SandyNotice(store.error, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                // زر إضافة لطيف (مو "+" عارية).
                SandyButton(title: lang.s("life.habits.add"), systemImage: "flame.fill", fillWidth: true) {
                    showAdd = true
                }
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.vertical, Theme.Spacing.md)
                .disabled(store.demo)
                .opacity(store.demo ? 0.5 : 1)

                if store.loading && store.habits.isEmpty {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else if store.habits.isEmpty {
                    LivelyEmptyState(
                        line: lang.s("life.habits.empty"),
                        mood: .happy)
                    Spacer()
                } else {
                    List {
                        ForEach(store.habits) { habit in
                            habitRow(habit)
                                .listRowBackground(Color.clear)
                                .listRowSeparator(.hidden)
                                .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                          bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                                .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                    if !store.demo {
                                        Button(role: .destructive) {
                                            store.delete(api: state.api, habit: habit)
                                        } label: { Label(lang.s("life.habits.delete"), systemImage: "trash") }
                                    }
                                }
                                .swipeActions(edge: .leading) {
                                    if !store.demo {
                                        Button { editingHabit = habit } label: {
                                            Label(lang.s("life.habits.edit"), systemImage: "pencil")
                                        }
                                        .tint(Theme.Colors.accent)
                                    }
                                }
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.habits.count)
                }
            }
        }
        .navigationTitle(lang.s("life.habits"))
        .fullScreenCover(isPresented: $showAdd) {
            HabitSheet { name in
                try await store.add(api: state.api, name: name)
            }
        }
        .fullScreenCover(item: $editingHabit) { habit in
            HabitSheet(existing: habit) { name in
                try await store.rename(api: state.api, habit: habit, name: name)
            }
        }
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
    }

    @ViewBuilder
    private func habitRow(_ habit: HabitItem) -> some View {
        let isCelebrating = celebratingID == habit.id
        HStack(spacing: Theme.Spacing.md) {
            Button {
                if habit.doneToday {
                    store.uncheckin(api: state.api, habit: habit)
                } else {
                    celebrate(habit.id)
                    store.checkin(api: state.api, habit: habit)
                }
            } label: {
                Image(systemName: habit.doneToday ? "checkmark.circle.fill" : "circle")
                    .font(.title2)
                    .foregroundColor(habit.doneToday ? Theme.Colors.success : Theme.Colors.secondaryText)
                    // نبضة لطيفة لحظة تسجيل الحضور.
                    .scaleEffect(isCelebrating ? 1.3 : 1.0)
                    .animation(.spring(response: 0.3, dampingFraction: 0.5), value: isCelebrating)
            }
            .buttonStyle(.plain)
            .disabled(store.demo)

            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(habit.name)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                HStack(spacing: Theme.Spacing.xs) {
                    Text(String(format: lang.s("life.habits.streak"), "\(habit.streak)"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(habit.streak > 0 ? Theme.Colors.accentDeep : Theme.Colors.secondaryText)
                    if habit.doneToday {
                        Text(lang.s("life.habits.doneToday"))
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.success)
                    }
                }
            }
            Spacer(minLength: 0)

            // وميض احتفالي صغير يطلع لحظة تسجيل الحضور.
            if isCelebrating {
                Image(systemName: "sparkles")
                    .font(.title3)
                    .foregroundColor(Theme.Colors.accent)
                    .transition(.scale.combined(with: .opacity))
            }
        }
        .sandyCard()
        // وميض الاحتفال يبقى عبر النبضة/الـ sparkles فقط — بلا توهّج بطاقة إضافي.
        .scaleEffect(isCelebrating ? 1.02 : 1.0)
        .animation(.spring(response: 0.35, dampingFraction: 0.6), value: isCelebrating)
        .contentShape(Rectangle())
        .onTapGesture { if !store.demo { editingHabit = habit } }
        .contextMenu {
            if !store.demo {
                Button { editingHabit = habit } label: {
                    Label(lang.s("life.habits.edit"), systemImage: "pencil")
                }
                Button(role: .destructive) {
                    store.delete(api: state.api, habit: habit)
                } label: { Label(lang.s("life.habits.delete"), systemImage: "trash") }
            }
        }
    }

    /// احتفال السلسلة (واجهة بحتة) — يضيء لحظة تسجيل الحضور ثم يهدأ.
    private func celebrate(_ id: String) {
        withAnimation(.spring(response: 0.3, dampingFraction: 0.5)) {
            celebratingID = id
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.1) {
            withAnimation { if celebratingID == id { celebratingID = nil } }
        }
    }
}

/// شيت إضافة عادة: اسم + تكرار (يومي/أسبوعي) للمساعدة على وضوح النية.
/// ملاحظة: الباك-إند يستقبل الاسم فقط (addHabit(name:))، فالتكرار يُدمج بالاسم
/// كلاحقة وصفية بسيطة حتى ما نضيف حقولًا غير مدعومة — تفصيل بدون كسر العقد.
struct HabitSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    /// العادة القائمة عند التعديل (nil = إضافة). بالتعديل = إعادة تسمية فقط.
    let existing: HabitItem?
    /// يستقبل اسم العادة (مع لاحقة التكرار إن اختيرت) ويرمي عند الفشل.
    let onSave: (String) async throws -> Void

    /// التكرار: عرضه مترجَم عبر مفتاح l10n، لكن اللاحقة المُرسَلة للباك-إند تبقى
    /// قيمة عربية قانونية ثابتة (لاحقة الاسم) — لا نكسر عقد التخزين الحالي.
    enum Frequency: String, CaseIterable, Identifiable {
        case daily, weekly
        var id: String { rawValue }
        /// مفتاح l10n لعرض اسم التكرار (للعرض فقط).
        var labelKey: String { self == .daily ? "life.habits.freq.daily" : "life.habits.freq.weekly" }
    }

    /// لاحقة "أسبوعي" القانونية الثابتة المُرسَلة للباك-إند كجزء من اسم العادة.
    /// تبقى عربية بغض النظر عن لغة الواجهة حتى ما نكسر عقد الاسم/السجلّات القديمة.
    private static let weeklyCanonicalSuffix = "(أسبوعي)"

    @State private var name: String
    @State private var frequency: Frequency = .daily
    @State private var saving = false
    @State private var error = ""

    init(existing: HabitItem? = nil, onSave: @escaping (String) async throws -> Void) {
        self.existing = existing
        self.onSave = onSave
        _name = State(initialValue: existing?.name ?? "")
    }

    private var isEditing: Bool { existing != nil }
    private var trimmedName: String { name.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        SandyPopup(title: lang.s(isEditing ? "life.habits.editTitle" : "life.habits.add")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("life.habits.sheet.nameSection"))
                    SandyCard {
                        TextField(lang.s("life.habits.sheet.namePlaceholder"), text: $name)
                            .font(Theme.Typography.body)
                    }
                }
                // التكرار للإضافة فقط — التعديل إعادة تسمية صرفة.
                if !isEditing {
                    VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                        SectionHeader(title: lang.s("life.habits.sheet.freqSection"))
                        Picker(lang.s("life.habits.sheet.freqLabel"), selection: $frequency) {
                            ForEach(Frequency.allCases) { f in
                                Text(lang.s(f.labelKey)).tag(f)
                            }
                        }
                        .pickerStyle(.segmented)
                    }
                }
                if !error.isEmpty {
                    SandyNotice(error, kind: .gentleWarning)
                }
                SandyButton(title: lang.s("common.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: saving,
                            fillWidth: true) {
                    save()
                }
                .disabled(trimmedName.isEmpty)
                .opacity(trimmedName.isEmpty ? 0.5 : 1)
            }
            .animation(.easeInOut(duration: 0.25), value: error)
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard !trimmedName.isEmpty else { return }
        saving = true
        withAnimation { error = "" }
        // التعديل = إعادة تسمية صرفة (بدون لمس لاحقة التكرار). الإضافة فقط تدمج
        // لاحقة "أسبوعي" القانونية الثابتة حتى ما نكسر عقد الاسم بالباك-إند.
        let finalName = (!isEditing && frequency == .weekly)
            ? "\(trimmedName) \(Self.weeklyCanonicalSuffix)"
            : trimmedName
        Task {
            do {
                try await onSave(finalName)
                dismiss()
            } catch {
                withAnimation { self.error = lang.s("life.habits.saveError") }
            }
            saving = false
        }
    }
}
