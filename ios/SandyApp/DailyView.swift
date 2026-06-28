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
        HubRowSpec(icon: "flame.fill", titleKey: "daily.habits",
                   subtitleKey: "daily.habits.subtitle", tint: Theme.Colors.success),
        HubRowSpec(icon: "target", titleKey: "daily.focus",
                   subtitleKey: "daily.focus.subtitle", tint: Theme.Colors.accentDeep),
    ]

    var body: some View {
        HubList(rows: rows) { index in
            switch index {
            case 0:  TasksView()
            case 1:  RemindersView()
            case 2:  HabitsView()
            default: FocusView()
            }
        }
        .navigationTitle(lang.s("daily.title"))
    }
}
