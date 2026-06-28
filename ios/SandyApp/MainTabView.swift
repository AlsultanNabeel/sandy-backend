import SwiftUI

/// تبويبات ساندي الأربعة (Core-4). الترتيب ثابت ومرتبط بـ `selection` حتى نقدر
/// نبدّل التبويب برمجيًّا (مثلاً HomeView يقفز لتبويب ساندي).
///
/// • الرئيسية — مدخل ساندي الحيّ ولوحة المعلومات.
/// • ساندي    — مركز الذكاء الموحّد (محادثة + بحث + صور بمكان واحد).
/// • يومي     — التخطيط (المهام + التذكيرات + العادات + الفوكس).
/// • حياتي    — المعنى والذكريات (اليوميات + المصاريف).
///
/// ملاحظة: الحساب (ProfileView) مش تبويب — نوصله من زر أفاتار بالرئيسية،
/// وفيه أرشيف ساندي (الذاكرة + الخط الزمني + الروبوت).
enum MainTab: Int, Hashable, CaseIterable {
    case home, sandy, daily, life

    var icon: String {
        switch self {
        case .home:  return "house.fill"
        case .sandy: return "sparkles"
        case .daily: return "calendar"
        case .life:  return "heart.text.square.fill"
        }
    }

    var titleKey: String {
        switch self {
        case .home:  return "tabs.home"
        case .sandy: return "tabs.sandy"
        case .daily: return "tabs.daily"
        case .life:  return "tabs.life"
        }
    }
}

/// الواجهة الرئيسية بعد الدخول — أربعة تبويبات (الرئيسية مدخل ساندي الحيّ).
/// نخفي شريط آبل المصمت ونستبدله بشريط ساندي الزجاجي الطافي بالأسفل.
struct MainTabView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    /// التبويب المختار — مصدر الحقيقة للتبديل البرمجي.
    @State private var selection: MainTab = .home

    var body: some View {
        // فوتر حقيقي: التبويبات بصف فوق، وشريط ساندي بصف تحت — فما في إشي
        // (حقل كتابة، أزرار) بيجي وراه. الشريط نفسه كبسولة زجاجية بهوامش فتحسّها طايفة.
        VStack(spacing: 0) {
            TabView(selection: $selection) {
                NavigationStack { HomeView(selection: $selection) }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.home)

                NavigationStack { SandyHubView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.sandy)

                NavigationStack { DailyView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.daily)

                NavigationStack { LifeView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.life)
            }
            // رفيق ساندي العائم — فوق منطقة المحتوى فقط (مش فوق الفوتر).
            .overlay {
                SandyCompanionLayer(tab: selection) {
                    withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
                        selection = .sandy
                    }
                }
            }

            // الفوتر يتجاهل الكيبورد (يغطّيه الكيبورد بدل ما يرتفع فوقه)، وحقل
            // الكتابة جوّا التبويبات بيطلع فوق الكيبورد عادي.
            FloatingTabBar(selection: $selection)
                .ignoresSafeArea(.keyboard, edges: .bottom)
        }
        // خلفية ساندي تحت الفوتر وهوامشه.
        .background(SandyBackground())
        .task { await state.refreshOnboarding() }
    }
}

// MARK: - شريط التبويبات الزجاجي الطافي (ليكويد جلاس)

/// شريط تبويبات يطفو فوق المحتوى — كبسولة زجاجية مموّهة بحافة لمعان وظل يرفعها
/// عن الشاشة (تحسّها طايفة بالهوا). مع أربعة تبويبات بس، كلهن ظاهرين دفعة وحدة
/// بصف ثابت (بلا تمرير) — نقرة وحدة لأي تبويب. المختار يصير كبسولة أزرق فيها
/// أيقونة + اسم، والباقي أيقونات هادئة.
struct FloatingTabBar: View {
    @Binding var selection: MainTab
    @EnvironmentObject var lang: LanguageManager

    var body: some View {
        HStack(spacing: Theme.Spacing.xs) {
            ForEach(MainTab.allCases, id: \.self) { tab in
                tabButton(tab)
                    .frame(maxWidth: .infinity)
            }
        }
        .padding(6)
        // كبسولة زجاج سائل (نفس معدِّن البطاقات) + ظل رفع قوي ليطفو.
        .liquidGlass(cornerRadius: Theme.Radius.pill, tint: 0.08)
        .shadow(color: Theme.Shadow.liftColor,
                radius: Theme.Shadow.liftRadius, x: 0, y: Theme.Shadow.liftY)
        .padding(.horizontal, Theme.Spacing.lg)
        .padding(.bottom, Theme.Spacing.sm)
    }

    @ViewBuilder
    private func tabButton(_ tab: MainTab) -> some View {
        let selected = selection == tab
        Button {
            withAnimation(.spring(response: 0.4, dampingFraction: 0.78)) { selection = tab }
        } label: {
            HStack(spacing: Theme.Spacing.xs) {
                Image(systemName: tab.icon)
                    .font(.system(size: 17, weight: .semibold))
                // الاسم يظهر فقط للتبويب المختار (كبسولة تتمدّد).
                if selected {
                    Text(lang.s(tab.titleKey))
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .lineLimit(1)
                        .fixedSize()
                }
            }
            .foregroundColor(selected ? Theme.Colors.onAccent : Theme.Colors.secondaryText)
            .padding(.vertical, 10)
            .padding(.horizontal, selected ? Theme.Spacing.md : 12)
            .background {
                if selected {
                    Capsule().fill(
                        LinearGradient(
                            colors: [Theme.Colors.accent, Theme.Colors.accentDeep],
                            startPoint: .topLeading, endPoint: .bottomTrailing))
                }
            }
            .clipShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(lang.s(tab.titleKey))
    }
}
