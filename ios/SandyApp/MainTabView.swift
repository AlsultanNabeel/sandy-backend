import SwiftUI

/// تبويبات ساندي الخمسة. الترتيب ثابت ومرتبط بـ `selection` حتى نقدر نبدّل
/// التبويب برمجيًّا (مثلاً HomeView يقفز لتبويب الشات).
///
/// ملاحظة: الحساب (ProfileView) مش تبويب — نوصله من زر أفاتار بالرئيسية.
enum MainTab: Int, Hashable, CaseIterable {
    case home, chat, search, images, tasks, reminders, life, focus, robot, memory

    var icon: String {
        switch self {
        case .home:      return "house.fill"
        case .chat:      return "bubble.left.and.bubble.right.fill"
        case .search:    return "magnifyingglass"
        case .images:    return "photo.artframe"
        case .tasks:     return "checklist"
        case .reminders: return "bell.fill"
        case .life:      return "heart.text.square.fill"
        case .focus:     return "target"
        case .robot:     return "av.remote.fill"
        case .memory:    return "brain"
        }
    }

    var titleKey: String {
        switch self {
        case .home:      return "tabs.home"
        case .chat:      return "tabs.chat"
        case .search:    return "tabs.search"
        case .images:    return "tabs.images"
        case .tasks:     return "tabs.tasks"
        case .reminders: return "tabs.reminders"
        case .life:      return "tabs.life"
        case .focus:     return "tabs.focus"
        case .robot:     return "tabs.robot"
        case .memory:    return "tabs.memory"
        }
    }
}

/// الواجهة الرئيسية بعد الدخول — خمسة تبويبات (الرئيسية مدخل ساندي الحيّ).
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

                NavigationStack { ChatView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.chat)

                NavigationStack { SearchView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.search)

                NavigationStack { ImagesView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.images)

                NavigationStack { TasksView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.tasks)

                NavigationStack { RemindersView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.reminders)

                NavigationStack { LifeView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.life)

                NavigationStack { FocusView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.focus)

                NavigationStack { RobotView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.robot)

                NavigationStack { MemoryView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.memory)
            }
            // رفيق ساندي العائم — فوق منطقة المحتوى فقط (مش فوق الفوتر).
            .overlay {
                SandyCompanionLayer(tab: selection) {
                    withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
                        selection = .chat
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
/// عن الشاشة (تحسّها طايفة بالهوا). التبويب المختار يصير كبسولة أزرق فيها أيقونة
/// + اسم، والباقي أيقونات هادئة. يقابل شريط آبل الطافي الجديد لكن بأزرقنا.
struct FloatingTabBar: View {
    @Binding var selection: MainTab
    @EnvironmentObject var lang: LanguageManager

    var body: some View {
        // قابل للتمرير أفقيًا ليستوعب كل التبويبات (زي صف كبسولات الويب).
        ScrollViewReader { proxy in
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Theme.Spacing.xs) {
                    ForEach(MainTab.allCases, id: \.self) { tab in
                        tabButton(tab).id(tab)
                    }
                }
                .padding(6)
            }
            // كبسولة زجاج سائل (نفس معدِّن البطاقات) + ظل رفع قوي ليطفو.
            .liquidGlass(cornerRadius: Theme.Radius.pill, tint: 0.08)
            .shadow(color: Theme.Shadow.liftColor,
                    radius: Theme.Shadow.liftRadius, x: 0, y: Theme.Shadow.liftY)
            .padding(.horizontal, Theme.Spacing.lg)
            .padding(.bottom, Theme.Spacing.sm)
            // التبويب المختار يزحف للوسط حتى يضل ظاهر.
            .onChange(of: selection) { tab in
                withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
                    proxy.scrollTo(tab, anchor: .center)
                }
            }
        }
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
