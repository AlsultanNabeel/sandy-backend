import SwiftUI

/// تبويب يومي — صار شبكة ويدجت قابلة للتخصيص (ترتيب/إخفاء/تكبير) بدل قائمة ثابتة.
/// كل ميزة ويدجت؛ الكود كله موجود، والشبكة بس بتقرّر الشكل. المالك يقدر يخفي أي
/// ميزة مركزياً من السيرفر (state.serverHiddenFeatures).
struct DailyView: View {
    @EnvironmentObject var lang: LanguageManager
    @EnvironmentObject var state: AppState
    @StateObject private var store = DashboardStore(id: "daily", catalog: DailyView.catalog)

    /// كتالوج ميزات يومي — المفتاح ثابت (يطابق مفتاح الإخفاء بالسيرفر)، مع وجهته.
    static let catalog: [WidgetSpec] = [
        WidgetSpec(key: "tasks", icon: "checklist", titleKey: "daily.tasks",
                   tint: Theme.Colors.accent) { AnyView(TasksView()) },
        WidgetSpec(key: "reminders", icon: "bell.fill", titleKey: "daily.reminders",
                   tint: Theme.Colors.warn) { AnyView(RemindersView()) },
        WidgetSpec(key: "goals", icon: "flag.fill", titleKey: "daily.goals",
                   tint: Theme.Colors.accentDeep) { AnyView(GoalsView()) },
        WidgetSpec(key: "habits", icon: "flame.fill", titleKey: "daily.habits",
                   tint: Theme.Colors.success) { AnyView(HabitsView()) },
        WidgetSpec(key: "focus", icon: "target", titleKey: "daily.focus",
                   tint: Theme.Colors.accent) { AnyView(FocusView()) },
        WidgetSpec(key: "future", icon: "envelope.fill", titleKey: "daily.future",
                   tint: Theme.Colors.warn) { AnyView(FutureMessagesView()) },
    ]

    var body: some View {
        WidgetDashboard(store: store)
            .navigationTitle(lang.s("daily.title"))
            .onAppear { store.applyServerHidden(state.serverHiddenFeatures) }
            .onChange(of: state.serverHiddenFeatures) { store.applyServerHidden($0) }
    }
}
