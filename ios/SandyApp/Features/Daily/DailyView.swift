import SwiftUI

/// تبويب يومي — صار شبكة ويدجت قابلة للتخصيص (ترتيب/إخفاء/تكبير) بدل قائمة ثابتة.
/// كل ميزة ويدجت؛ الكود كله موجود، والشبكة بس بتقرّر الشكل. المالك يقدر يخفي أي
/// ميزة مركزياً من السيرفر (state.serverHiddenFeatures).
struct DailyView: View {
    @EnvironmentObject var lang: LanguageManager
    @EnvironmentObject var state: AppState

    /// ميزات يومي. المفتاح ثابت ويطابق مفتاح الإخفاء بالسيرفر — المالك بيقدر
    /// يخفي أي ميزة مركزيًا، وساعتها ما بتوصل اللوح أصلًا.
    private struct Feature {
        let key: String, icon: String, titleKey: String
        let tint: Color, size: CardSize
        let destination: () -> AnyView
        var preview: (() -> AnyView)?
    }

    private var features: [Feature] {
        [
            Feature(key: "tasks", icon: "checklist", titleKey: "daily.tasks",
                    tint: Theme.Colors.accent, size: .large,
                    destination: { AnyView(TasksView()) },
                    preview: { AnyView(TasksWidget()) }),
            Feature(key: "reminders", icon: "bell.fill", titleKey: "daily.reminders",
                    tint: Theme.Colors.warn, size: .small,
                    destination: { AnyView(RemindersView()) }),
            Feature(key: "goals", icon: "flag.fill", titleKey: "daily.goals",
                    tint: Theme.Colors.accentDeep, size: .small,
                    destination: { AnyView(GoalsView()) }),
            Feature(key: "habits", icon: "flame.fill", titleKey: "daily.habits",
                    tint: Theme.Colors.success, size: .small,
                    destination: { AnyView(HabitsView()) }),
            Feature(key: "focus", icon: "target", titleKey: "daily.focus",
                    tint: Theme.Colors.accent, size: .small,
                    destination: { AnyView(FocusView()) }),
            Feature(key: "future", icon: "envelope.fill", titleKey: "daily.future",
                    tint: Theme.Colors.warn, size: .small,
                    destination: { AnyView(FutureMessagesView()) }),
        ].filter { !state.serverHiddenFeatures.contains($0.key) }
    }

    var body: some View {
        CardBoard("daily") {
            features.map { f in
                BoardCard(f.key, titleKey: f.titleKey, icon: f.icon,
                          defaultSize: f.size) {
                    NavigationLink { f.destination() } label: {
                        if let preview = f.preview {
                            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                                HubRowCard(spec: HubRowSpec(icon: f.icon,
                                                            titleKey: f.titleKey,
                                                            subtitleKey: f.titleKey + ".subtitle",
                                                            tint: f.tint))
                                preview()
                            }
                        } else {
                            HubRowCard(spec: HubRowSpec(icon: f.icon,
                                                        titleKey: f.titleKey,
                                                        subtitleKey: f.titleKey + ".subtitle",
                                                        tint: f.tint))
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .navigationTitle(lang.s("daily.title"))
    }
}
