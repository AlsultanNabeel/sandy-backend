import SwiftUI

/// ملخّص الأسبوع — بطاقات الأرقام (هالأسبوع مقابل الماضي) + جملة ساندي.
/// بيفتح من بطاقة «ملخّص الأسبوع» بيومي، ومن إشعار الأحد المسائي.
struct InsightsView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = InsightsStore()

    private let columns = [
        GridItem(.flexible(), spacing: Theme.Spacing.md),
        GridItem(.flexible(), spacing: Theme.Spacing.md),
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                }
                if store.demo {
                    SandyNotice(lang.s("insights.demo"), kind: .info)
                }

                sandyCard

                Text(lang.s("insights.range"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.tertiaryText)
                    .padding(.horizontal, Theme.Spacing.xs)

                LazyVGrid(columns: columns, spacing: Theme.Spacing.md) {
                    ForEach(store.metrics) { m in
                        InsightMetricCard(metric: m)
                    }
                }

                if let streak = store.insights?.bestStreak, streak > 0 {
                    streakCard(streak)
                }

                if store.loading && store.insights == nil {
                    ProgressView()
                        .tint(Theme.Colors.accent)
                        .frame(maxWidth: .infinity)
                        .padding(.top, Theme.Spacing.lg)
                }
            }
            .padding(Theme.Spacing.md)
            .animation(.easeInOut(duration: 0.25), value: store.insights)
        }
        .background(SandyBackground())
        .navigationTitle(lang.s("insights.title"))
        .task { await store.load(api: state.api) }
        .refreshable {
            Haptics.play(.selection)
            await store.load(api: state.api)
        }
    }

    /// جملة ساندي عن الأسبوع — أول إشي بالشاشة.
    @ViewBuilder
    private var sandyCard: some View {
        if let text = store.insights?.sentence, !text.isEmpty {
            HStack(alignment: .top, spacing: Theme.Spacing.md) {
                SandyAvatar(size: 44, mood: .happy)
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(lang.s("insights.sandySays"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.accent)
                    Text(text)
                        .font(Theme.Typography.body)
                        .foregroundColor(Theme.Colors.primaryText)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .sandyCard(.primary)
        }
    }

    private func streakCard(_ streak: Int) -> some View {
        HStack(spacing: Theme.Spacing.md) {
            Image(systemName: "flame.fill")
                .font(.system(size: Theme.Icon.lg, weight: .semibold))
                .foregroundColor(Theme.Colors.warn)
            Text(lang.s("insights.bestStreak"))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
            Spacer(minLength: 0)
            Text(String(format: lang.s("insights.days"), AppLocale.number(streak)))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.warn)
        }
        .sandyCard()
    }
}

/// بطاقة رقم واحد: أيقونة + اسم + الرقم + التغيّر عن الأسبوع الماضي.
struct InsightMetricCard: View {
    @EnvironmentObject var lang: LanguageManager
    let metric: InsightMetric

    /// المصاريف: النزول هو الخبر الحلو، فبنقلب اللون.
    private var lowerIsBetter: Bool { metric.key == "expenses_total" }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            HStack(spacing: Theme.Spacing.sm) {
                Image(systemName: Self.icon(metric.key))
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(Self.tint(metric.key))
                Text(lang.s("insights.metric.\(metric.key)"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .lineLimit(2)
                    .minimumScaleFactor(0.85)
            }
            Text(format(metric.current))
                .font(Theme.Typography.title)
                .foregroundColor(Theme.Colors.primaryText)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            deltaChip
            Text(String(format: lang.s("insights.vsLast"), format(metric.previous)))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.tertiaryText)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .sandyCard()
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private var deltaChip: some View {
        let diff = metric.current - metric.previous
        if diff == 0 {
            chip(icon: "equal", text: lang.s("insights.same"), color: Theme.Colors.tertiaryText)
        } else if let change = metric.change {
            let up = diff > 0
            let good = up != lowerIsBetter
            chip(icon: up ? "arrow.up.right" : "arrow.down.right",
                 text: percent(abs(change)),
                 color: good ? Theme.Colors.success : Theme.Colors.warn)
        } else {
            chip(icon: "sparkles", text: lang.s("insights.new"), color: Theme.Colors.accent)
        }
    }

    private func chip(icon: String, text: String, color: Color) -> some View {
        HStack(spacing: Theme.Spacing.xs) {
            Image(systemName: icon)
                .font(.system(size: 11, weight: .bold))
            Text(text)
                .font(Theme.Typography.caption)
                .lineLimit(1)
        }
        .foregroundColor(color)
        .padding(.horizontal, Theme.Spacing.sm)
        .padding(.vertical, 3)
        .background(Capsule().fill(color.opacity(0.14)))
    }

    private func format(_ v: Double) -> String {
        metric.key == "expenses_total"
            ? AppLocale.number(v, minFraction: 0, maxFraction: 2)
            : AppLocale.number(Int(v.rounded()))
    }

    private func percent(_ fraction: Double) -> String {
        AppLocale.number(Int((fraction * 100).rounded())) + (AppLocale.isArabic ? "٪" : "%")
    }

    static func icon(_ key: String) -> String {
        switch key {
        case "tasks_completed":  return "checkmark.circle.fill"
        case "reminders_done":   return "bell.fill"
        case "focus_minutes":    return "target"
        case "habit_checkins":   return "flame.fill"
        case "expenses_total":   return "creditcard.fill"
        case "journal_entries":  return "book.closed.fill"
        case "reading_pages":    return "book.fill"
        case "reading_sessions": return "bookmark.fill"
        case "chat_turns":       return "bubble.left.and.bubble.right.fill"
        default:                 return "chart.bar.fill"
        }
    }

    static func tint(_ key: String) -> Color {
        switch key {
        case "tasks_completed", "habit_checkins": return Theme.Colors.success
        case "reminders_done", "expenses_total":  return Theme.Colors.warn
        case "journal_entries", "reading_pages", "reading_sessions": return Theme.Colors.accentDeep
        default: return Theme.Colors.accent
        }
    }
}
