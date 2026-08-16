import SwiftUI

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
        .onChange(of: store.summary.total) { _, newValue in
            withAnimation(.easeOut(duration: 0.6)) { animatedTotal = newValue }
        }
    }

    private var summaryCard: some View {
        HStack {
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(lang.s("life.expenses.summaryTitle"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                Text(String(format: "%.0f", animatedTotal))
                    .font(Theme.Typography.largeTitle)
                    .foregroundColor(Theme.Colors.accentDeep)
                    .monospacedDigit()
                    .contentTransition(.numericText())
            }
            Spacer(minLength: 0)
            // شارة عدد الحركات.
            VStack(spacing: Theme.Spacing.xs) {
                Image(systemName: "list.bullet.rectangle")
                    .foregroundColor(Theme.Colors.accent)
                Text(String(format: lang.s("life.expenses.count"), "\(store.summary.count)"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.tertiaryText)
            }
        }
        .sandyCard(.primary)
        .sandyGlow()
    }

    @ViewBuilder
    private func expenseRow(_ item: ExpenseItem) -> some View {
        HStack(spacing: Theme.Spacing.md) {
            // أيقونة تصنيف ملوّنة خفيفة.
            ZStack {
                Circle()
                    .fill(Theme.Colors.secondary.opacity(0.12))
                    .frame(width: Theme.Icon.xl, height: Theme.Icon.xl)
                Image(systemName: categoryIcon(item.category))
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(Theme.Colors.secondary)
            }
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                // العنوان: الملاحظة إن وُجدت، وإلا اسم التصنيف المترجَم (للعرض فقط)،
                // وإلا "مصروف". القيمة المخزّنة (item.category) تبقى قانونية كما هي.
                Text(item.note.isEmpty
                     ? (item.category.isEmpty
                        ? lang.s("life.expenses.fallbackTitle")
                        : LifeCategories.label(for: item.category, lang))
                     : item.note)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                if !item.category.isEmpty && !item.note.isEmpty {
                    Text(LifeCategories.label(for: item.category, lang))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.tertiaryText)
                }
            }
            Spacer(minLength: 0)
            Text(String(format: "%.0f", item.amount))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
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
struct ExpenseSheet: View {
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
