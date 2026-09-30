import SwiftUI

/// تبويب يومي — لوح بطاقات: قائمة لكل قائمة بجدول الأنواع (مهام، تسوق، أهداف...)
/// وبطاقة للتذكيرات. قائمة جديدة بالسيرفر بتظهر هون بدون كود.
/// المالك بيقدر يخفي أي بطاقة مركزياً (state.serverHiddenFeatures) باسمها.
struct DailyView: View {
    @EnvironmentObject var lang: LanguageManager
    @EnvironmentObject var state: AppState
    @ObservedObject private var kinds = KindsStore.shared

    private let tints = [Theme.Colors.accent, Theme.Colors.success, Theme.Colors.warn,
                         Theme.Colors.accentDeep]

    var body: some View {
        CardBoard("daily") {
            reminderCard
            focusCard
            futureCard
            kinds.lists.filter { !state.serverHiddenFeatures.contains($0.name) }
                .enumerated().map { index, kind in
                    // A kind's label is already translated; lang.s passes a dot-less string through.
                    BoardCard(kind.name, titleKey: kind.label(lang.lang), icon: kind.icon,
                              defaultSize: .small) {
                        NavigationLink { ItemsView(kind: kind) } label: {
                            DailyRow(icon: kind.icon, title: kind.label(lang.lang),
                                     tint: tints[index % tints.count])
                        }
                        .buttonStyle(.plain)
                    }
                }
        }
        .navigationTitle(lang.s("daily.title"))
        .task { await kinds.load(api: state.api) }
    }

    private var reminderCard: [BoardCard] {
        guard !state.serverHiddenFeatures.contains("reminders") else { return [] }
        return [BoardCard("reminders", titleKey: "blocks.reminders", icon: "bell.fill",
                          defaultSize: .small) {
            NavigationLink { SchedulesView() } label: {
                DailyRow(icon: "bell.fill", title: lang.s("blocks.reminders"), tint: Theme.Colors.warn)
            }
            .buttonStyle(.plain)
        }]
    }
}

extension DailyView {
    /// Focus sessions stay their own screen: they drive the lock-screen Live Activity.
    fileprivate var focusCard: [BoardCard] {
        guard !state.serverHiddenFeatures.contains("focus") else { return [] }
        return [BoardCard("focus", titleKey: "daily.focus", icon: "target", defaultSize: .small) {
            NavigationLink { FocusView() } label: {
                DailyRow(icon: "target", title: lang.s("daily.focus"), tint: Theme.Colors.accent)
            }
            .buttonStyle(.plain)
        }]
    }

    fileprivate var futureCard: [BoardCard] {
        guard !state.serverHiddenFeatures.contains("future") else { return [] }
        return [BoardCard("future", titleKey: "daily.future", icon: "envelope.fill",
                          defaultSize: .small) {
            NavigationLink { SchedulesView(kind: "message_to_future_self") } label: {
                DailyRow(icon: "envelope.fill", title: lang.s("daily.future"), tint: Theme.Colors.warn)
            }
            .buttonStyle(.plain)
        }]
    }
}

private struct DailyRow: View {
    let icon: String
    let title: String
    let tint: Color

    var body: some View {
        HStack(spacing: Theme.Spacing.md) {
            ZStack {
                Circle().fill(tint.opacity(0.14)).frame(width: 44, height: 44)
                Image(systemName: icon)
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(tint)
            }
            Text(title)
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
            Spacer(minLength: 0)
            Image(systemName: "chevron.forward")
                .font(.system(size: Theme.Icon.sm, weight: .semibold))
                .foregroundColor(Theme.Colors.tertiaryText)
        }
        .sandyCard()
    }
}
