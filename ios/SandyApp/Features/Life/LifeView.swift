import SwiftUI

/// تبويب حياتي — شريط الشهر، قوائمك، وسجلّ كل اللي صار مع بحث وفلتر وملخّص عند الطلب.
struct LifeView: View {
    var body: some View { LogView(isLife: true) }
}

/// My Life's numbers from the server (the whole log), kept on disk, plus what was made
/// on the phone since they were counted.
@MainActor
final class LifeStatsStore: ObservableObject {
    static let shared = LifeStatsStore()
    @Published private var counted: LifeStats?
    private var countedAt = Date.distantPast
    /// Set on the phone and not counted by the server yet.
    @Published private var localBudget: Double?

    var stats: LifeStats {
        var out = (counted ?? LifeStats(days: Array(repeating: 0, count: 30), spent: 0, habits: 0,
                                        logged: 0, byCategory: [:], budget: 0))
            .including(LogStore.madeSince(countedAt))
        if let localBudget { out.budget = localBudget }
        return out
    }

    /// Signed out: the next account starts from nothing, not from these numbers.
    func reset() {
        counted = nil
        countedAt = .distantPast
        localBudget = nil
    }

    func setBudget(api: APIClient, _ amount: Double) {
        localBudget = amount
        Task { try? await api.setBudget(amount) }
    }

    /// Called after an expense is added on the phone: a notification when this month's
    /// spending crosses 80% or 100% of the limit.
    func checkBudget(adding amount: Double) {
        let now = stats
        guard let budget = now.budget, budget > 0 else { return }
        let before = now.spent - amount
        for (share, key) in [(1.0, "life.budget.over"), (0.8, "life.budget.near")]
        where before < budget * share && now.spent >= budget * share {
            NotificationManager.shared.notifyNow(
                title: LanguageManager.shared.s("life.budget.title"),
                body: String(format: LanguageManager.shared.s(key),
                             AppLocale.number(Int(now.spent.rounded())), AppLocale.number(Int(budget.rounded()))))
            return
        }
    }

    func load(api: APIClient) async {
        if counted == nil, let cached = DiskCache.load(LifeStats.self, key: "life.stats",
                                                       userId: api.currentUserId) {
            counted = cached
        }
        let session = AccountSession.generation
        guard Outbox.shared.isEmpty, let fresh = try? await api.stats(),
              session == AccountSession.generation else { return }
        countedAt = Date()
        counted = fresh
        localBudget = nil
        DiskCache.save(fresh, key: "life.stats", userId: api.currentUserId)
    }
}

/// Top of My Life: thirty days as lit squares (how much you logged each day), then your
/// reminders, lists and messages to your future self as cards you swipe through.
struct LifeHeader: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject private var kinds = KindsStore.shared
    let stats: LifeStats
    /// The day picked on the strip; the log below shows only it.
    @Binding var day: Date?
    @Environment(\.dynamicTypeSize) private var typeSize
    @State private var projects: [String] = []
    /// Opens the spending sheet (presented by the screen, not from inside a list row).
    let openSpending: () -> Void

    private var perDay: [Int] { stats.days }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            OneTimeTip(tip: LifeDayTip())
            monthStrip
            monthNumbers
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Theme.Spacing.sm) {
                    NavigationLink { SchedulesView() } label: {
                        card(icon: "bell.fill", title: lang.s("blocks.reminders"))
                    }
                    .buttonStyle(.plain)
                    ForEach(kinds.lists) { k in
                        NavigationLink { ItemsView(kind: k) } label: {
                            card(icon: k.icon, title: k.label(lang.lang))
                        }
                        .buttonStyle(.plain)
                    }
                    // Projects Sandy keeps from chat, a card each (there is no fixed list of them).
                    ForEach(projects, id: \.self) { list in
                        let name = String(list.dropFirst("project:".count))
                        NavigationLink {
                            ItemsView(kind: BlockKind(name: list, block: .list, labels: ["ar": name, "en": name],
                                                      icon: "folder.fill", prefix: false))
                        } label: {
                            card(icon: "folder.fill", title: name)
                        }
                        .buttonStyle(.plain)
                    }
                    NavigationLink { SchedulesView(kind: "message_to_future_self") } label: {
                        card(icon: "envelope.fill", title: lang.s("blocks.future"))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(.vertical, Theme.Spacing.sm)
        .task { projects = (try? await state.api.projectLists()) ?? projects }
    }

    private var monthStrip: some View {
        let counts = perDay
        let top = max(counts.max() ?? 1, 1)
        return VStack(alignment: .leading, spacing: 6) {
            Text(lang.s("life.month"))
                .scaledFont(13, weight: .semibold, design: .rounded)
                .foregroundColor(Theme.Colors.tertiaryText)
            HStack(spacing: 3) {
                ForEach(Array(counts.enumerated()), id: \.offset) { i, n in
                    let date = dayAt(i)
                    let picked = day.map { Calendar.current.isDate($0, inSameDayAs: date) } ?? false
                    RoundedRectangle(cornerRadius: 3)
                        .fill(n == 0 ? Theme.Colors.surface.opacity(0.6)
                              : Theme.Colors.accent.opacity(0.25 + 0.75 * Double(n) / Double(top)))
                        .frame(height: picked ? 30 : 22)
                        .overlay(i == 29 || picked ? RoundedRectangle(cornerRadius: 3)
                            .stroke(picked ? Theme.Colors.accent : Theme.Colors.primaryText.opacity(0.6),
                                    lineWidth: picked ? 2 : 1) : nil)
                        .contentShape(Rectangle())
                        .onTapGesture {
                            Haptics.play(.selection)
                            withAnimation(Animation.spring(response: 0.35).reduced) { day = picked ? nil : date }
                        }
                        .accessibilityElement()
                        .accessibilityLabel(String(format: lang.s("a11y.dayStrip"),
                            date.formatted(Date.FormatStyle(date: .abbreviated, time: .omitted)
                                .locale(AppLocale.current)), AppLocale.number(n)))
                        .accessibilityHint(lang.s("a11y.dayStripHint"))
                        .accessibilityAddTraits(picked ? [.isButton, .isSelected] : .isButton)
                }
            }
            .frame(height: 30)
            if let day {
                HStack(spacing: Theme.Spacing.sm) {
                    Text(day.formatted(Date.FormatStyle(date: .complete, time: .omitted).locale(AppLocale.current)))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Button { withAnimation { self.day = nil } } label: {
                        Image(systemName: "xmark.circle.fill").foregroundColor(Theme.Colors.tertiaryText)
                    }
                    .accessibilityLabel(lang.s("life.showAll"))
                }
                .transition(.opacity)
            }
        }
    }

    private func dayAt(_ index: Int) -> Date {
        let cal = Calendar.current
        return cal.date(byAdding: .day, value: index - 29, to: cal.startOfDay(for: Date())) ?? Date()
    }

    /// This month at a glance: what you spent and how many things you logged.
    /// Three cards in a row; one under the other at the largest text sizes.
    private var monthNumbers: some View {
        let layout = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(spacing: Theme.Spacing.sm))
                                                  : AnyLayout(HStackLayout(spacing: Theme.Spacing.sm))
        return layout {
            Button(action: openSpending) {
                stat(icon: "creditcard.fill", value: AppLocale.number(Int(stats.spent.rounded())),
                     key: "life.stat.spent", progress: budgetShare)
            }
            .buttonStyle(.plain)
            stat(icon: "flame.fill", value: AppLocale.number(stats.habits), key: "life.stat.habits")
            stat(icon: "square.stack.fill", value: AppLocale.number(stats.logged), key: "life.stat.logged")
        }
    }

    /// This month's spending against the limit, nil when there is none.
    private var budgetShare: Double? {
        guard let budget = stats.budget, budget > 0 else { return nil }
        return stats.spent / budget
    }

    private func stat(icon: String, value: String, key: String, progress: Double? = nil) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Image(systemName: icon)
                .scaledFont(13, weight: .semibold)
                .foregroundColor(Theme.Colors.accent)
            Text(value)
                .scaledFont(20, weight: .bold, design: .rounded)
                .foregroundColor(Theme.Colors.primaryText)
            Text(lang.s(key))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
                .lineLimit(1)
            if let progress {
                BudgetBar(share: progress).padding(.top, 4)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Theme.Spacing.sm + 2)
        .liquidGlass(cornerRadius: 14)
    }

    private func card(icon: String, title: String) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Image(systemName: icon)
                .scaledFont(Theme.Icon.md, weight: .semibold)
                .foregroundColor(Theme.Colors.accent)
            Text(title)
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.primaryText)
                .lineLimit(1)
        }
        .frame(width: 84 * DisplaySettings.shared.elementScale, alignment: .leading)
        .padding(Theme.Spacing.sm + 2)
        .liquidGlass(cornerRadius: 16)
    }
}

// MARK: - حالة فاضية حيّة (مشتركة)

/// حالة فاضية ودودة: أفاتار ساندي + سطر تشجيع عربي — بدل أيقونة باهتة.
/// تطفو بنعومة لتعطي إحساس بالحياة.
struct LivelyEmptyState: View {
    let line: String
    var mood: SandyAvatar.Mood = .happy

    @State private var bob = false

    var body: some View {
        VStack(spacing: Theme.Spacing.md) {
            SandyAvatar(size: 64, mood: mood)
                .offset(y: bob ? -6 : 0)
                .animation(Animation.easeInOut(duration: 2.2).repeatForever(autoreverses: true).reduced, value: bob)
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

/// Spent against the limit: green, amber from 80%, red past it.
struct BudgetBar: View {
    let share: Double

    var body: some View {
        // Scaled, not measured: a GeometryReader in a list row re-lays the row while it
        // scrolls, which shook My Life on pull-to-refresh.
        Capsule()
            .fill(Theme.Colors.surface.opacity(0.8))
            .overlay(alignment: .leading) {
                Capsule()
                    .fill(share >= 1 ? Theme.Colors.danger : share >= 0.8 ? Theme.Colors.warn : Theme.Colors.success)
                    .scaleEffect(x: min(max(share, 0), 1), anchor: .leading)
            }
            .frame(height: 5)
    }
}

/// This month's spending: the limit (set here), and what went where.
struct SpendingSheet: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let stats: LifeStats
    @State private var budget = ""

    private var categories: [(String, Double)] {
        (stats.byCategory ?? [:]).sorted { $0.value > $1.value }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section(lang.s("life.budget.limit")) {
                    TextField(lang.s("life.budget.none"), text: $budget).keyboardType(.decimalPad)
                    if let limit = stats.budget, limit > 0 {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(String(format: lang.s("life.budget.used"),
                                        AppLocale.number(Int(stats.spent.rounded())),
                                        AppLocale.number(Int(limit.rounded()))))
                                .font(Theme.Typography.subheadline)
                            BudgetBar(share: stats.spent / limit)
                        }
                    }
                }
                Section(lang.s("life.budget.where")) {
                    if categories.isEmpty {
                        Text(lang.s("life.budget.empty")).foregroundColor(Theme.Colors.secondaryText)
                    }
                    ForEach(categories, id: \.0) { name, amount in
                        HStack {
                            Label(lang.s("blocks.cat." + name), systemImage: ExpenseCategory.icon(name))
                            Spacer()
                            Text(AppLocale.number(Int(amount.rounded())))
                                .font(Theme.Typography.headline)
                        }
                    }
                }
            }
            .navigationTitle(lang.s("life.stat.spent"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("blocks.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.s("blocks.save")) {
                        let value = Digits.number(budget) ?? 0
                        LifeStatsStore.shared.setBudget(api: state.api, value)
                        dismiss()
                    }
                }
            }
            .onAppear {
                if let limit = stats.budget, limit > 0 { budget = String(Int(limit.rounded())) }
            }
        }
        .presentationDetents([.medium, .large])
    }
}
