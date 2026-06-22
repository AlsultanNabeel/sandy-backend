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
    @State private var habits: [HabitItem] = []
    @State private var loading = false
    @State private var error = ""
    @State private var demo = false
    @State private var showAdd = false
    /// آيدي العادة التي سُجّل حضورها للتو — يشغّل أنميشن الاحتفال بالسلسلة.
    @State private var celebratingID: String? = nil

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if demo { DemoBanner() }

                if !error.isEmpty {
                    SandyNotice(error, kind: .gentleWarning)
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
                .disabled(demo)
                .opacity(demo ? 0.5 : 1)

                if loading && habits.isEmpty {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else if habits.isEmpty {
                    LivelyEmptyState(
                        line: lang.s("life.habits.empty"),
                        mood: .happy)
                    Spacer()
                } else {
                    ScrollView {
                        VStack(spacing: Theme.Spacing.sm) {
                            ForEach(habits) { habit in
                                habitRow(habit)
                                    .transition(.asymmetric(
                                        insertion: .scale(scale: 0.92).combined(with: .opacity),
                                        removal: .opacity))
                            }
                        }
                        .padding(Theme.Spacing.md)
                        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: habits.count)
                    }
                }
            }
        }
        .navigationTitle(lang.s("life.habits"))
        .sheet(isPresented: $showAdd) {
            AddHabitSheet { name in
                try await state.api.addHabit(name: name)
                await load()
            }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    @ViewBuilder
    private func habitRow(_ habit: HabitItem) -> some View {
        let isCelebrating = celebratingID == habit.id
        HStack(spacing: Theme.Spacing.md) {
            Button {
                if habit.doneToday { uncheckin(habit) } else { checkin(habit) }
            } label: {
                Image(systemName: habit.doneToday ? "checkmark.circle.fill" : "circle")
                    .font(.title2)
                    .foregroundColor(habit.doneToday ? Theme.Colors.success : Theme.Colors.secondaryText)
                    // نبضة لطيفة لحظة تسجيل الحضور.
                    .scaleEffect(isCelebrating ? 1.3 : 1.0)
                    .animation(.spring(response: 0.3, dampingFraction: 0.5), value: isCelebrating)
            }
            .buttonStyle(.plain)
            .disabled(demo)

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
    }

    private func load() async {
        loading = true
        withAnimation { error = "" }
        do {
            let r = try await state.api.getHabits()
            withAnimation { habits = r.items }
            demo = r.demo
        } catch {
            withAnimation { self.error = lang.s("life.habits.loadError") }
        }
        loading = false
    }

    private func checkin(_ habit: HabitItem) {
        guard !habit.doneToday else { return }
        // نشغّل الاحتفال فورًا (قبل ما يرجع السيرفر) ليكون الإحساس فوري.
        withAnimation(.spring(response: 0.3, dampingFraction: 0.5)) {
            celebratingID = habit.id
        }
        // نطفّي الاحتفال بعد لحظة لطيفة.
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.1) {
            withAnimation { if celebratingID == habit.id { celebratingID = nil } }
        }
        Task {
            do {
                try await state.api.checkinHabit(name: habit.name)
                await load()
            } catch {
                withAnimation { self.error = lang.s("life.habits.checkinError") }
            }
        }
    }

    // تراجع عن تسجيل حضور اليوم (لو انضغط بالغلط).
    private func uncheckin(_ habit: HabitItem) {
        guard habit.doneToday else { return }
        Task {
            do {
                try await state.api.uncheckinHabit(id: habit.id)
                await load()
            } catch {
                withAnimation { self.error = lang.s("life.habits.checkinError") }
            }
        }
    }
}

/// شيت إضافة عادة: اسم + تكرار (يومي/أسبوعي) للمساعدة على وضوح النية.
/// ملاحظة: الباك-إند يستقبل الاسم فقط (addHabit(name:))، فالتكرار يُدمج بالاسم
/// كلاحقة وصفية بسيطة حتى ما نضيف حقولًا غير مدعومة — تفصيل بدون كسر العقد.
private struct AddHabitSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
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

    @State private var name = ""
    @State private var frequency: Frequency = .daily
    @State private var saving = false
    @State private var error = ""

    private var trimmedName: String { name.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        NavigationStack {
            Form {
                Section(lang.s("life.habits.sheet.nameSection")) {
                    TextField(lang.s("life.habits.sheet.namePlaceholder"), text: $name)
                }
                Section(lang.s("life.habits.sheet.freqSection")) {
                    Picker(lang.s("life.habits.sheet.freqLabel"), selection: $frequency) {
                        ForEach(Frequency.allCases) { f in
                            Text(lang.s(f.labelKey)).tag(f)
                        }
                    }
                    .pickerStyle(.segmented)
                }
                if !error.isEmpty {
                    Section {
                        SandyNotice(error, kind: .gentleWarning)
                            .listRowInsets(EdgeInsets())
                            .listRowBackground(Color.clear)
                    }
                }
            }
            .navigationTitle(lang.s("life.habits.add"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("common.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(lang.s("common.save")) { save() }
                        .disabled(saving || trimmedName.isEmpty)
                }
            }
        }
    }

    private func save() {
        guard !trimmedName.isEmpty else { return }
        saving = true
        withAnimation { error = "" }
        // ندمج التكرار كلاحقة وصفية فقط لو أسبوعي (اليومي هو الافتراضي الطبيعي للعادات).
        // اللاحقة المُرسَلة تبقى عربية قانونية ثابتة حتى ما نكسر عقد الاسم بالباك-إند.
        let finalName = frequency == .weekly
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
    @State private var items: [ExpenseItem] = []
    @State private var summary = ExpensesSummary(total: 0, count: 0)
    @State private var loading = false
    @State private var error = ""
    @State private var demo = false
    @State private var showAdd = false
    /// المجموع المعروض — نحرّكه نحو القيمة الحقيقية ليبان "عدّاد حيّ".
    @State private var animatedTotal: Double = 0

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if demo { DemoBanner() }

                if !error.isEmpty {
                    SandyNotice(error, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                SandyButton(title: lang.s("life.expenses.add"), systemImage: "plus.circle.fill", fillWidth: true) {
                    showAdd = true
                }
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.vertical, Theme.Spacing.md)
                .disabled(demo)
                .opacity(demo ? 0.5 : 1)

                if loading && items.isEmpty {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else {
                    ScrollView {
                        VStack(spacing: Theme.Spacing.sm) {
                            summaryCard
                            if items.isEmpty {
                                LivelyEmptyState(
                                    line: lang.s("life.expenses.empty"),
                                    mood: .soft)
                            } else {
                                ForEach(items) { item in
                                    expenseRow(item)
                                        .transition(.asymmetric(
                                            insertion: .move(edge: .top).combined(with: .opacity),
                                            removal: .opacity))
                                }
                            }
                        }
                        .padding(Theme.Spacing.md)
                        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: items.count)
                    }
                }
            }
        }
        .navigationTitle(lang.s("life.expenses"))
        .sheet(isPresented: $showAdd) {
            AddExpenseSheet { amount, note, category in
                try await state.api.addExpense(amount: amount, note: note, category: category)
                await load()
            }
        }
        .task { await load() }
        .refreshable { await load() }
        // عدّاد المجموع المتحرّك: كل ما تتغيّر القيمة الحقيقية، ننزلق إليها بنعومة.
        // نستعمل صيغة onChange ذات الباراميتر الواحد (iOS 16) كما ببقية المشروع.
        .onChange(of: summary.total) { newValue in
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
                Text(String(format: lang.s("life.expenses.count"), "\(summary.count)"))
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

    private func load() async {
        loading = true
        withAnimation { error = "" }
        do {
            let r = try await state.api.getExpenses()
            withAnimation { items = r.items }
            summary = r.summary
            demo = r.demo
        } catch {
            withAnimation { self.error = lang.s("life.expenses.loadError") }
        }
        loading = false
    }
}

/// شيت إضافة مصروف: مبلغ (رقمي) + تصنيف (Picker بتصنيفات عربية شائعة) + ملاحظة.
private struct AddExpenseSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    /// يستقبل (المبلغ، الملاحظة، التصنيف) ويرمي عند الفشل.
    let onSave: (Double, String, String) async throws -> Void

    // التصنيفات: القيم القانونية العربية (LifeCategories.canonical) هي اللي تنحفظ
    // وتُرسَل للباك-إند — لا تُترجَم أبداً. للعرض فقط نعرض label مترجَم عبر مفتاح l10n.

    @State private var amount = ""
    @State private var note = ""
    /// القيمة القانونية المختارة (عربية) — أوّل واحدة هي الافتراضي، كما كان سابقاً.
    @State private var category = LifeCategories.canonical.first ?? ""
    @State private var saving = false
    @State private var error = ""

    private var amountValue: Double {
        Double(amount.trimmingCharacters(in: .whitespaces)) ?? 0
    }

    var body: some View {
        NavigationStack {
            Form {
                Section(lang.s("life.expenses.sheet.amountSection")) {
                    HStack {
                        Image(systemName: "banknote")
                            .foregroundColor(Theme.Colors.accent)
                        TextField(lang.s("life.expenses.sheet.amountPlaceholder"), text: $amount)
                            .keyboardType(.decimalPad)
                            .font(.system(size: 22, weight: .semibold, design: .rounded))
                    }
                }
                Section(lang.s("life.expenses.sheet.categorySection")) {
                    Picker(lang.s("life.expenses.sheet.categoryLabel"), selection: $category) {
                        // نختار القيمة القانونية (tag) لكن نعرض label مترجَم.
                        ForEach(LifeCategories.canonical, id: \.self) { c in
                            Text(LifeCategories.label(for: c, lang)).tag(c)
                        }
                    }
                    .pickerStyle(.menu)
                }
                Section(lang.s("life.expenses.sheet.noteSection")) {
                    TextField(lang.s("life.expenses.sheet.notePlaceholder"), text: $note)
                }
                if !error.isEmpty {
                    Section {
                        SandyNotice(error, kind: .gentleWarning)
                            .listRowInsets(EdgeInsets())
                            .listRowBackground(Color.clear)
                    }
                }
            }
            .navigationTitle(lang.s("life.expenses.sheet.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("common.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(lang.s("common.save")) { save() }
                        .disabled(saving || amountValue <= 0)
                }
            }
        }
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
    @State private var entries: [JournalEntry] = []
    @State private var loading = false
    @State private var error = ""
    @State private var demo = false
    @State private var showAdd = false

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if demo { DemoBanner() }

                if !error.isEmpty {
                    SandyNotice(error, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                SandyButton(title: lang.s("life.journal.add"), systemImage: "square.and.pencil", fillWidth: true) {
                    showAdd = true
                }
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.vertical, Theme.Spacing.md)
                .disabled(demo)
                .opacity(demo ? 0.5 : 1)

                if loading && entries.isEmpty {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else if entries.isEmpty {
                    LivelyEmptyState(
                        line: lang.s("life.journal.empty"),
                        mood: .happy)
                    Spacer()
                } else {
                    ScrollView {
                        VStack(spacing: Theme.Spacing.sm) {
                            ForEach(entries) { entry in
                                entryRow(entry)
                                    .transition(.asymmetric(
                                        insertion: .move(edge: .top).combined(with: .opacity),
                                        removal: .opacity))
                            }
                        }
                        .padding(Theme.Spacing.md)
                        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: entries.count)
                    }
                }
            }
        }
        .navigationTitle(lang.s("life.journal"))
        .sheet(isPresented: $showAdd) {
            AddJournalSheet { text in
                try await state.api.addJournalEntry(text: text)
                await load()
            }
        }
        .task { await load() }
        .refreshable { await load() }
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
    }

    private func load() async {
        loading = true
        withAnimation { error = "" }
        do {
            let r = try await state.api.getJournal()
            withAnimation { entries = r.items }
            demo = r.demo
        } catch {
            withAnimation { self.error = lang.s("life.journal.loadError") }
        }
        loading = false
    }
}

/// شيت إضافة خاطرة: محرّر متعدّد الأسطر مريح + عدّاد أحرف خفيف.
private struct AddJournalSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    /// يستقبل النص ويرمي عند الفشل.
    let onSave: (String) async throws -> Void

    @State private var text = ""
    @State private var saving = false
    @State private var error = ""

    private var trimmed: String { text.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        NavigationStack {
            Form {
                Section(lang.s("life.journal.sheet.section")) {
                    TextField(lang.s("life.journal.sheet.placeholder"), text: $text, axis: .vertical)
                        .lineLimit(6...14)
                        .font(.body)
                }
                Section {
                    HStack {
                        Spacer(minLength: 0)
                        Text(String(format: lang.s("life.journal.sheet.charCount"), "\(trimmed.count)"))
                            .font(.caption2)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                    .listRowBackground(Color.clear)
                }
                if !error.isEmpty {
                    Section {
                        SandyNotice(error, kind: .gentleWarning)
                            .listRowInsets(EdgeInsets())
                            .listRowBackground(Color.clear)
                    }
                }
            }
            .navigationTitle(lang.s("life.journal.sheet.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("common.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(lang.s("common.save")) { save() }
                        .disabled(saving || trimmed.isEmpty)
                }
            }
        }
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
