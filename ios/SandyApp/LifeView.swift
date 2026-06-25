import SwiftUI

/// تبويب حياتي — لوحة فيها روابط لـ العادات/المصاريف/اليوميات (بدل زحمة التبويبات).
/// مُحدّثة: بطاقات حيّة (دخول متدرّج)، أزرار إضافة لطيفة بأسماء وأيقونات،
/// شيتات إضافة أغنى، أخطاء بصوت ساندي (SandyNotice)، وحالات فاضية ودودة.
struct LifeView: View {
    @EnvironmentObject var lang: LanguageManager

    /// نتحكّم بظهور البطاقات لعمل دخول متدرّج لطيف عند فتح اللوحة.
    @State private var appeared = false

    /// أوصاف صفوف اللوحة — نلفّها بمصفوفة لنعطي كل صف تأخير دخول مختلف.
    /// العناوين/الأوصاف تُترجَم عند العرض عبر مفاتيح l10n (نخزّن المفاتيح لا النص).
    private let rows: [HubRowSpec] = [
        HubRowSpec(icon: "flame.fill", titleKey: "life.habits",
                   subtitleKey: "life.habits.subtitle", tint: Theme.Colors.accent),
        HubRowSpec(icon: "creditcard.fill", titleKey: "life.expenses",
                   subtitleKey: "life.expenses.subtitle", tint: Theme.Colors.success),
        HubRowSpec(icon: "book.closed.fill", titleKey: "life.journal",
                   subtitleKey: "life.journal.subtitle", tint: Theme.Colors.warn),
    ]

    var body: some View {
        ZStack {
            SandyBackground()

            ScrollView {
                VStack(spacing: Theme.Spacing.md) {
                    ForEach(Array(rows.enumerated()), id: \.element.id) { index, spec in
                        NavigationLink {
                            destination(for: index)
                        } label: {
                            hubRow(spec)
                        }
                        .buttonStyle(.plain)
                        // دخول متدرّج: كل بطاقة تطلع بنعومة بتأخير بسيط حسب ترتيبها.
                        .opacity(appeared ? 1 : 0)
                        .offset(y: appeared ? 0 : 16)
                        .animation(.spring(response: 0.5, dampingFraction: 0.8)
                                    .delay(Double(index) * 0.08),
                                   value: appeared)
                    }
                }
                .padding(Theme.Spacing.md)
            }
        }
        .navigationTitle(lang.s("life.title"))
        .onAppear { appeared = true }
    }

    @ViewBuilder
    private func destination(for index: Int) -> some View {
        switch index {
        case 0: HabitsView()
        case 1: ExpensesView()
        default: JournalView()
        }
    }

    @ViewBuilder
    private func hubRow(_ spec: HubRowSpec) -> some View {
        HStack(spacing: Theme.Spacing.md) {
            // أيقونة داخل دائرة ملوّنة خفيفة — أدفأ من أيقونة عارية.
            ZStack {
                Circle()
                    .fill(spec.tint.opacity(0.14))
                    .frame(width: 44, height: 44)
                Image(systemName: spec.icon)
                    .font(.title3)
                    .foregroundColor(spec.tint)
            }
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(lang.s(spec.titleKey))
                    .font(.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                Text(lang.s(spec.subtitleKey))
                    .font(.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.left")
                .foregroundColor(Theme.Colors.secondaryText)
        }
        .sandyCard()
    }
}

/// وصف صف لوحة (أيقونة/مفتاح عنوان/مفتاح وصف/لون) — يسهّل عمل الدخول المتدرّج بـ ForEach.
/// نخزّن مفاتيح l10n لا النص نفسه حتى تتبدّل اللغة بدون إعادة بناء المصفوفة.
private struct HubRowSpec: Identifiable {
    let id = UUID()
    let icon: String
    let titleKey: String
    let subtitleKey: String
    let tint: Color
}

// MARK: - العادات

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
        ZStack {
            SandyBackground()

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
                    .font(.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                HStack(spacing: Theme.Spacing.xs) {
                    Text(String(format: lang.s("life.habits.streak"), "\(habit.streak)"))
                        .font(.caption)
                        .foregroundColor(habit.streak > 0 ? Theme.Colors.accentDeep : Theme.Colors.secondaryText)
                    if habit.doneToday {
                        Text(lang.s("life.habits.doneToday"))
                            .font(.caption2)
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
        // توهّج خفيف حول البطاقة لحظة الاحتفال.
        .shadow(color: isCelebrating ? Theme.Shadow.glowColor : .clear,
                radius: isCelebrating ? Theme.Shadow.glowRadius : 0)
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
private struct HabitSheet: View {
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

// MARK: - المصاريف

/// شاشة المصاريف — ملخّص حيّ بمجموع متحرّك + قائمة + شيت إضافة أغنى (مبلغ/تصنيف/ملاحظة).
struct ExpensesView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    /// مصدر الحقيقة للمصاريف (يملك البيانات + الجلب + الإضافة، مستقل عن الشاشة).
    @StateObject private var store = ExpensesStore()
    @State private var showAdd = false
    /// المصروف الجاري تعديله (nil = ما في ورقة تعديل مفتوحة).
    @State private var editingExpense: ExpenseItem?
    /// المجموع المعروض — نحرّكه نحو القيمة الحقيقية ليبان "عدّاد حيّ".
    @State private var animatedTotal: Double = 0

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if store.demo { DemoBanner() }

                if !store.error.isEmpty {
                    SandyNotice(store.error, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                SandyButton(title: lang.s("life.expenses.add"), systemImage: "plus.circle.fill", fillWidth: true) {
                    showAdd = true
                }
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.vertical, Theme.Spacing.md)
                .disabled(store.demo)
                .opacity(store.demo ? 0.5 : 1)

                if store.loading && store.items.isEmpty {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else {
                    List {
                        // الملخّص صف غير قابل للسحب يبقى أعلى القائمة.
                        summaryCard
                            .listRowBackground(Color.clear)
                            .listRowSeparator(.hidden)
                            .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                      bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                        if store.items.isEmpty {
                            LivelyEmptyState(line: lang.s("life.expenses.empty"), mood: .soft)
                                .listRowBackground(Color.clear)
                                .listRowSeparator(.hidden)
                        } else {
                            ForEach(store.items) { item in
                                expenseRow(item)
                                    .listRowBackground(Color.clear)
                                    .listRowSeparator(.hidden)
                                    .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                              bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                                    .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                        if !store.demo {
                                            Button(role: .destructive) {
                                                store.delete(api: state.api, item: item)
                                            } label: { Label(lang.s("life.expenses.delete"), systemImage: "trash") }
                                        }
                                    }
                                    .swipeActions(edge: .leading) {
                                        if !store.demo {
                                            Button { editingExpense = item } label: {
                                                Label(lang.s("life.expenses.edit"), systemImage: "pencil")
                                            }
                                            .tint(Theme.Colors.accent)
                                        }
                                    }
                            }
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.items.count)
                }
            }
        }
        .navigationTitle(lang.s("life.expenses"))
        .fullScreenCover(isPresented: $showAdd) {
            ExpenseSheet { amount, note, category in
                try await store.add(api: state.api, amount: amount, note: note, category: category)
            }
        }
        .fullScreenCover(item: $editingExpense) { item in
            ExpenseSheet(existing: item) { amount, note, category in
                try await store.update(api: state.api, id: item.id,
                                       amount: amount, note: note, category: category)
            }
        }
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        // عدّاد المجموع المتحرّك: كل ما تتغيّر القيمة الحقيقية، ننزلق إليها بنعومة.
        // نستعمل صيغة onChange ذات الباراميتر الواحد (iOS 16) كما ببقية المشروع.
        .onChange(of: store.summary.total) { newValue in
            withAnimation(.easeOut(duration: 0.6)) { animatedTotal = newValue }
        }
    }

    private var summaryCard: some View {
        HStack {
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(lang.s("life.expenses.summaryTitle"))
                    .font(.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                Text(String(format: "%.0f", animatedTotal))
                    .font(.system(size: 30, weight: .bold, design: .rounded))
                    .foregroundColor(Theme.Colors.accentDeep)
                    .monospacedDigit()
                    .contentTransition(.numericText())
            }
            Spacer(minLength: 0)
            // شارة عدد الحركات.
            VStack(spacing: 2) {
                Image(systemName: "list.bullet.rectangle")
                    .foregroundColor(Theme.Colors.accent)
                Text(String(format: lang.s("life.expenses.count"), "\(store.summary.count)"))
                    .font(.caption2)
                    .foregroundColor(Theme.Colors.secondaryText)
            }
        }
        .sandyCard()
    }

    @ViewBuilder
    private func expenseRow(_ item: ExpenseItem) -> some View {
        HStack(spacing: Theme.Spacing.md) {
            // أيقونة تصنيف ملوّنة خفيفة.
            ZStack {
                Circle()
                    .fill(Theme.Colors.accent.opacity(0.12))
                    .frame(width: 40, height: 40)
                Image(systemName: categoryIcon(item.category))
                    .foregroundColor(Theme.Colors.accent)
            }
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                // العنوان: الملاحظة إن وُجدت، وإلا اسم التصنيف المترجَم (للعرض فقط)،
                // وإلا "مصروف". القيمة المخزّنة (item.category) تبقى قانونية كما هي.
                Text(item.note.isEmpty
                     ? (item.category.isEmpty
                        ? lang.s("life.expenses.fallbackTitle")
                        : LifeCategories.label(for: item.category, lang))
                     : item.note)
                    .font(.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                if !item.category.isEmpty && !item.note.isEmpty {
                    Text(LifeCategories.label(for: item.category, lang))
                        .font(.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
            }
            Spacer(minLength: 0)
            Text(String(format: "%.0f", item.amount))
                .font(.system(size: 17, weight: .bold, design: .rounded))
                .foregroundColor(Theme.Colors.accent)
                .monospacedDigit()
        }
        .sandyCard()
        .contentShape(Rectangle())
        .onTapGesture { if !store.demo { editingExpense = item } }
        .contextMenu {
            if !store.demo {
                Button { editingExpense = item } label: {
                    Label(lang.s("life.expenses.edit"), systemImage: "pencil")
                }
                Button(role: .destructive) {
                    store.delete(api: state.api, item: item)
                } label: { Label(lang.s("life.expenses.delete"), systemImage: "trash") }
            }
        }
    }

    /// أيقونة لطيفة حسب التصنيف العربي (تطابق خيارات شيت الإضافة).
    private func categoryIcon(_ category: String) -> String {
        switch category {
        case "أكل":      return "fork.knife"
        case "مواصلات":  return "car.fill"
        case "تسوّق":    return "bag.fill"
        case "فواتير":   return "doc.text.fill"
        case "ترفيه":    return "gamecontroller.fill"
        default:          return "creditcard.fill"
        }
    }

}

/// شيت مصروف (إضافة أو تعديل): مبلغ (رقمي) + تصنيف (Picker بتصنيفات عربية شائعة)
/// + ملاحظة. `existing` غير nil ⇒ تعديل (تعبئة مسبقة).
private struct ExpenseSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    /// المصروف القائم عند التعديل (nil = إضافة جديدة).
    let existing: ExpenseItem?
    /// يستقبل (المبلغ، الملاحظة، التصنيف) ويرمي عند الفشل.
    let onSave: (Double, String, String) async throws -> Void

    // التصنيفات: القيم القانونية العربية (LifeCategories.canonical) هي اللي تنحفظ
    // وتُرسَل للباك-إند — لا تُترجَم أبداً. للعرض فقط نعرض label مترجَم عبر مفتاح l10n.

    @State private var amount: String
    @State private var note: String
    /// القيمة القانونية المختارة (عربية) — أوّل واحدة هي الافتراضي، كما كان سابقاً.
    @State private var category: String
    @State private var saving = false
    @State private var error = ""

    init(existing: ExpenseItem? = nil, onSave: @escaping (Double, String, String) async throws -> Void) {
        self.existing = existing
        self.onSave = onSave
        let amt = existing?.amount
        // أرقام صحيحة بلا كسور؛ غير ذلك نص خام — حتى المنتقي العشري يقبله.
        _amount = State(initialValue: amt.map { $0 == $0.rounded() ? String(Int($0)) : String($0) } ?? "")
        _note = State(initialValue: existing?.note ?? "")
        if let existing {
            // التصنيف الفاضي المخزّن يقابل "أخرى" بالواجهة (نفس مابِنغ الحفظ).
            _category = State(initialValue: existing.category.isEmpty ? LifeCategories.other : existing.category)
        } else {
            _category = State(initialValue: LifeCategories.canonical.first ?? "")
        }
    }

    private var isEditing: Bool { existing != nil }

    private var amountValue: Double {
        Double(amount.trimmingCharacters(in: .whitespaces)) ?? 0
    }

    var body: some View {
        SandyPopup(title: lang.s(isEditing ? "life.expenses.sheet.editTitle" : "life.expenses.sheet.title")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("life.expenses.sheet.amountSection"))
                    SandyCard {
                        HStack {
                            Image(systemName: "banknote")
                                .foregroundColor(Theme.Colors.accent)
                            TextField(lang.s("life.expenses.sheet.amountPlaceholder"), text: $amount)
                                .keyboardType(.decimalPad)
                                .font(.system(size: 22, weight: .semibold, design: .rounded))
                        }
                    }
                }
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("life.expenses.sheet.categorySection"))
                    SandyCard {
                        Picker(lang.s("life.expenses.sheet.categoryLabel"), selection: $category) {
                            // نختار القيمة القانونية (tag) لكن نعرض label مترجَم.
                            ForEach(LifeCategories.canonical, id: \.self) { c in
                                Text(LifeCategories.label(for: c, lang)).tag(c)
                            }
                        }
                        .pickerStyle(.menu)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("life.expenses.sheet.noteSection"))
                    SandyCard {
                        TextField(lang.s("life.expenses.sheet.notePlaceholder"), text: $note)
                            .font(Theme.Typography.body)
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
                .disabled(amountValue <= 0)
                .opacity(amountValue <= 0 ? 0.5 : 1)
            }
            .animation(.easeInOut(duration: 0.25), value: error)
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard amountValue > 0 else {
            withAnimation { error = lang.s("life.expenses.amountError") }
            return
        }
        saving = true
        withAnimation { error = "" }
        let n = note.trimmingCharacters(in: .whitespaces)
        // "أخرى" بنخليها تصنيف فاضي حتى ما تظهر كنص حرفي بالقائمة.
        // نقارن مع القيمة القانونية لا نص معروض — العقد مع الباك-إند يبقى ثابتاً.
        let c = category == LifeCategories.other ? "" : category
        Task {
            do {
                try await onSave(amountValue, n, c)
                dismiss()
            } catch {
                withAnimation { self.error = lang.s("life.expenses.saveError") }
            }
            saving = false
        }
    }
}

// MARK: - اليوميات

/// شاشة اليوميات — تعرض التدوينات مع شيت إضافة مريح (محرّر متعدّد الأسطر).
struct JournalView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    /// مصدر الحقيقة لليوميات (يملك البيانات + الجلب + الإضافة، مستقل عن الشاشة).
    @StateObject private var store = JournalStore()
    @State private var showAdd = false
    /// الخاطرة الجاري تعديلها (nil = ما في ورقة تعديل مفتوحة).
    @State private var editingEntry: JournalEntry?

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if store.demo { DemoBanner() }

                if !store.error.isEmpty {
                    SandyNotice(store.error, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                SandyButton(title: lang.s("life.journal.add"), systemImage: "square.and.pencil", fillWidth: true) {
                    showAdd = true
                }
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.vertical, Theme.Spacing.md)
                .disabled(store.demo)
                .opacity(store.demo ? 0.5 : 1)

                if store.loading && store.entries.isEmpty {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else if store.entries.isEmpty {
                    LivelyEmptyState(
                        line: lang.s("life.journal.empty"),
                        mood: .happy)
                    Spacer()
                } else {
                    List {
                        ForEach(store.entries) { entry in
                            entryRow(entry)
                                .listRowBackground(Color.clear)
                                .listRowSeparator(.hidden)
                                .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                          bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                                .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                    if !store.demo {
                                        Button(role: .destructive) {
                                            store.delete(api: state.api, entry: entry)
                                        } label: { Label(lang.s("life.journal.delete"), systemImage: "trash") }
                                    }
                                }
                                .swipeActions(edge: .leading) {
                                    if !store.demo {
                                        Button { editingEntry = entry } label: {
                                            Label(lang.s("life.journal.edit"), systemImage: "pencil")
                                        }
                                        .tint(Theme.Colors.accent)
                                    }
                                }
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.entries.count)
                }
            }
        }
        .navigationTitle(lang.s("life.journal"))
        .fullScreenCover(isPresented: $showAdd) {
            JournalSheet { text in
                try await store.add(api: state.api, text: text)
            }
        }
        .fullScreenCover(item: $editingEntry) { entry in
            JournalSheet(existing: entry) { text in
                try await store.update(api: state.api, id: entry.id, text: text)
            }
        }
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
    }

    @ViewBuilder
    private func entryRow(_ entry: JournalEntry) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            HStack(spacing: Theme.Spacing.xs) {
                Image(systemName: "quote.opening")
                    .font(.caption)
                    .foregroundColor(Theme.Colors.accent.opacity(0.6))
                if !entry.date.isEmpty {
                    Text(entry.date)
                        .font(.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
                Spacer(minLength: 0)
            }
            Text(entry.text)
                .font(.body)
                .foregroundColor(Theme.Colors.primaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
        .sandyCard()
        .contentShape(Rectangle())
        .onTapGesture { if !store.demo { editingEntry = entry } }
        .contextMenu {
            if !store.demo {
                Button { editingEntry = entry } label: {
                    Label(lang.s("life.journal.edit"), systemImage: "pencil")
                }
                Button(role: .destructive) {
                    store.delete(api: state.api, entry: entry)
                } label: { Label(lang.s("life.journal.delete"), systemImage: "trash") }
            }
        }
    }

}

/// شيت خاطرة (إضافة أو تعديل): محرّر متعدّد الأسطر مريح + عدّاد أحرف خفيف.
private struct JournalSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    /// الخاطرة القائمة عند التعديل (nil = إضافة جديدة).
    let existing: JournalEntry?
    /// يستقبل النص ويرمي عند الفشل.
    let onSave: (String) async throws -> Void

    @State private var text: String
    @State private var saving = false
    @State private var error = ""

    init(existing: JournalEntry? = nil, onSave: @escaping (String) async throws -> Void) {
        self.existing = existing
        self.onSave = onSave
        _text = State(initialValue: existing?.text ?? "")
    }

    private var isEditing: Bool { existing != nil }
    private var trimmed: String { text.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        SandyPopup(title: lang.s(isEditing ? "life.journal.sheet.editTitle" : "life.journal.sheet.title")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                SectionHeader(title: lang.s("life.journal.sheet.section"))
                SandyCard {
                    TextField(lang.s("life.journal.sheet.placeholder"), text: $text, axis: .vertical)
                        .lineLimit(5...12)
                        .font(.body)
                }
                HStack {
                    Spacer(minLength: 0)
                    Text(String(format: lang.s("life.journal.sheet.charCount"), "\(trimmed.count)"))
                        .font(.caption2)
                        .foregroundColor(Theme.Colors.secondaryText)
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
                .disabled(trimmed.isEmpty)
                .opacity(trimmed.isEmpty ? 0.5 : 1)
            }
            .animation(.easeInOut(duration: 0.25), value: error)
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard !trimmed.isEmpty else { return }
        saving = true
        withAnimation { error = "" }
        Task {
            do {
                try await onSave(trimmed)
                dismiss()
            } catch {
                withAnimation { self.error = lang.s("life.journal.saveError") }
            }
            saving = false
        }
    }
}

// MARK: - حالة فاضية حيّة (مشتركة)

/// حالة فاضية ودودة: أفاتار ساندي + سطر تشجيع عربي — بدل أيقونة باهتة.
/// تطفو بنعومة لتعطي إحساس بالحياة.
private struct LivelyEmptyState: View {
    let line: String
    var mood: SandyAvatar.Mood = .happy

    @State private var bob = false

    var body: some View {
        VStack(spacing: Theme.Spacing.md) {
            SandyAvatar(size: 64, mood: mood)
                .offset(y: bob ? -6 : 0)
                .animation(.easeInOut(duration: 2.2).repeatForever(autoreverses: true), value: bob)
            Text(line)
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Spacing.xl)
        .onAppear { bob = true }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// MARK: - الستورات (مصدر الحقيقة لكل قسم)
//
// كل ستور يملك بياناته + الجلب + التعديلات، مستقل عن دورة حياة الشاشة. الجلب
// بمهمة مملوكة للستور، فإلغاء إيماءة السحب/التنقّل ما يلغيه — والجديد يبيّن دايماً.

@MainActor
final class HabitsStore: ObservableObject {
    @Published var habits: [HabitItem] = []
    @Published var loading = false
    @Published var demo = false
    @Published var error = ""

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                let r = try await api.getHabits()
                withAnimation { habits = r.items }
                demo = r.demo
            } catch {
                if !error.isCancellation { withAnimation { self.error = LanguageManager.shared.s("life.habits.loadError") } }
            }
        }
        loadTask = task
        await task.value
    }

    func add(api: APIClient, name: String) async throws {
        try await api.addHabit(name: name)
        await load(api: api)
    }

    /// إعادة تسمية عادة ثم إعادة جلب — يرمي عند الفشل ليتعامل الشيت معه.
    func rename(api: APIClient, habit: HabitItem, name: String) async throws {
        try await api.renameHabit(id: habit.id, name: name)
        await load(api: api)
    }

    /// حذف تفاؤلي فوري ثم مصالحة عند الفشل.
    func delete(api: APIClient, habit: HabitItem) {
        withAnimation { habits.removeAll { $0.id == habit.id } }
        Task { @MainActor in
            do {
                try await api.deleteHabit(id: habit.id)
            } catch {
                withAnimation { self.error = LanguageManager.shared.s("life.habits.deleteError") }
                await load(api: api)
            }
        }
    }

    func checkin(api: APIClient, habit: HabitItem) {
        guard !habit.doneToday else { return }
        Task { @MainActor in
            do {
                try await api.checkinHabit(name: habit.name)
                await load(api: api)
            } catch {
                withAnimation { self.error = LanguageManager.shared.s("life.habits.checkinError") }
            }
        }
    }

    func uncheckin(api: APIClient, habit: HabitItem) {
        guard habit.doneToday else { return }
        Task { @MainActor in
            do {
                try await api.uncheckinHabit(id: habit.id)
                await load(api: api)
            } catch {
                withAnimation { self.error = LanguageManager.shared.s("life.habits.checkinError") }
            }
        }
    }
}

@MainActor
final class ExpensesStore: ObservableObject {
    @Published var items: [ExpenseItem] = []
    @Published var summary = ExpensesSummary(total: 0, count: 0)
    @Published var loading = false
    @Published var demo = false
    @Published var error = ""

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                let r = try await api.getExpenses()
                withAnimation { items = r.items }
                summary = r.summary
                demo = r.demo
            } catch {
                if !error.isCancellation { withAnimation { self.error = LanguageManager.shared.s("life.expenses.loadError") } }
            }
        }
        loadTask = task
        await task.value
    }

    func add(api: APIClient, amount: Double, note: String, category: String) async throws {
        try await api.addExpense(amount: amount, note: note, category: category)
        await load(api: api)
    }

    /// تعديل مصروف ثم إعادة جلب — يرمي عند الفشل ليتعامل الشيت معه.
    func update(api: APIClient, id: String, amount: Double, note: String, category: String) async throws {
        try await api.updateExpense(id: id, amount: amount, note: note, category: category)
        await load(api: api)
    }

    /// حذف تفاؤلي للعنصر والمجموع معًا (يبان حيّ)، ثم مصالحة مع السيرفر بإعادة جلب.
    func delete(api: APIClient, item: ExpenseItem) {
        withAnimation { items.removeAll { $0.id == item.id } }
        summary = ExpensesSummary(total: max(0, summary.total - item.amount),
                                  count: max(0, summary.count - 1))
        Task { @MainActor in
            do {
                try await api.deleteExpense(id: item.id)
            } catch {
                withAnimation { self.error = LanguageManager.shared.s("life.expenses.deleteError") }
            }
            await load(api: api)   // مصالحة المجموع/القائمة مع السيرفر بالحالتين
        }
    }
}

@MainActor
final class JournalStore: ObservableObject {
    @Published var entries: [JournalEntry] = []
    @Published var loading = false
    @Published var demo = false
    @Published var error = ""

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                let r = try await api.getJournal()
                withAnimation { entries = r.items }
                demo = r.demo
            } catch {
                if !error.isCancellation { withAnimation { self.error = LanguageManager.shared.s("life.journal.loadError") } }
            }
        }
        loadTask = task
        await task.value
    }

    func add(api: APIClient, text: String) async throws {
        try await api.addJournalEntry(text: text)
        await load(api: api)
    }

    /// تعديل نص خاطرة ثم إعادة جلب — يرمي عند الفشل ليتعامل الشيت معه.
    func update(api: APIClient, id: String, text: String) async throws {
        try await api.updateJournalEntry(id: id, text: text)
        await load(api: api)
    }

    /// حذف تفاؤلي فوري ثم مصالحة عند الفشل.
    func delete(api: APIClient, entry: JournalEntry) {
        withAnimation { entries.removeAll { $0.id == entry.id } }
        Task { @MainActor in
            do {
                try await api.deleteJournalEntry(id: entry.id)
            } catch {
                withAnimation { self.error = LanguageManager.shared.s("life.journal.deleteError") }
                await load(api: api)
            }
        }
    }
}
