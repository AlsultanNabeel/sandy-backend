import SwiftUI

/// تبويب حياتي — شريط الشهر، قوائمك، وسجلّ كل اللي صار مع بحث وفلتر وملخّص عند الطلب.
struct LifeView: View {
    var body: some View { LogView(isLife: true) }
}

/// My Life's numbers from the server (the whole log), kept on disk, plus what was made
/// on the phone since they were counted.
@MainActor
final class LifeStatsStore: ObservableObject {
    @Published private var counted: LifeStats?
    private var countedAt = Date.distantPast

    var stats: LifeStats {
        (counted ?? LifeStats(days: Array(repeating: 0, count: 30), spent: 0, habits: 0, logged: 0))
            .including(LogStore.madeSince(countedAt))
    }

    func load(api: APIClient) async {
        if counted == nil, let cached = DiskCache.load(LifeStats.self, key: "life.stats",
                                                       userId: api.currentUserId) {
            counted = cached
        }
        guard Outbox.shared.isEmpty, let fresh = try? await api.stats() else { return }
        countedAt = Date()
        counted = fresh
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

    private var perDay: [Int] { stats.days }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
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
                    NavigationLink { SchedulesView(kind: "message_to_future_self") } label: {
                        card(icon: "envelope.fill", title: lang.s("blocks.future"))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(.vertical, Theme.Spacing.sm)
    }

    private var monthStrip: some View {
        let counts = perDay
        let top = max(counts.max() ?? 1, 1)
        return VStack(alignment: .leading, spacing: 6) {
            Text(lang.s("life.month"))
                .font(.system(size: 13, weight: .semibold, design: .rounded))
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
                            withAnimation(.spring(response: 0.35)) { day = picked ? nil : date }
                        }
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
    private var monthNumbers: some View {
        HStack(spacing: Theme.Spacing.sm) {
            stat(icon: "creditcard.fill", value: AppLocale.number(Int(stats.spent.rounded())),
                 key: "life.stat.spent")
            stat(icon: "flame.fill", value: AppLocale.number(stats.habits), key: "life.stat.habits")
            stat(icon: "square.stack.fill", value: AppLocale.number(stats.logged), key: "life.stat.logged")
        }
    }

    private func stat(icon: String, value: String, key: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Image(systemName: icon)
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(Theme.Colors.accent)
            Text(value)
                .font(.system(size: 20, weight: .bold, design: .rounded))
                .foregroundColor(Theme.Colors.primaryText)
            Text(lang.s(key))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Theme.Spacing.sm + 2)
        .liquidGlass(cornerRadius: 14)
    }

    private func card(icon: String, title: String) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Image(systemName: icon)
                .font(.system(size: Theme.Icon.md, weight: .semibold))
                .foregroundColor(Theme.Colors.accent)
            Text(title)
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.primaryText)
                .lineLimit(1)
        }
        .frame(width: 84, alignment: .leading)
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
