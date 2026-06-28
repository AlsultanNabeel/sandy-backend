import SwiftUI

/// تبويب يومي — لوحة التخطيط: روابط لشاشات المهام/التذكيرات/العادات/الفوكس
/// (بدل زحمة التبويبات). تنضاف لها الأهداف والرسائل المجدولة لنفسك لاحقاً.
/// تستعمل نفس نمط الهَب المشترك (HubList) مثل تبويب حياتي.
struct DailyView: View {
    @EnvironmentObject var lang: LanguageManager

    private let rows: [HubRowSpec] = [
        HubRowSpec(icon: "checklist", titleKey: "daily.tasks",
                   subtitleKey: "daily.tasks.subtitle", tint: Theme.Colors.accent),
        HubRowSpec(icon: "bell.fill", titleKey: "daily.reminders",
                   subtitleKey: "daily.reminders.subtitle", tint: Theme.Colors.warn),
        HubRowSpec(icon: "flag.fill", titleKey: "daily.goals",
                   subtitleKey: "daily.goals.subtitle", tint: Theme.Colors.accentDeep),
        HubRowSpec(icon: "flame.fill", titleKey: "daily.habits",
                   subtitleKey: "daily.habits.subtitle", tint: Theme.Colors.success),
        HubRowSpec(icon: "target", titleKey: "daily.focus",
                   subtitleKey: "daily.focus.subtitle", tint: Theme.Colors.accent),
        HubRowSpec(icon: "envelope.fill", titleKey: "daily.future",
                   subtitleKey: "daily.future.subtitle", tint: Theme.Colors.warn),
    ]

    var body: some View {
        HubList(rows: rows) { index in
            switch index {
            case 0:  TasksView()
            case 1:  RemindersView()
            case 2:  GoalsView()
            case 3:  HabitsView()
            case 4:  FocusView()
            default: FutureMessagesView()
            }
        }
        .navigationTitle(lang.s("daily.title"))
    }
}
