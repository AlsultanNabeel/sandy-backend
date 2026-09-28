import SwiftUI

/// الترتيب ثابت ومرتبط بـ `selection` حتى نقدر نبدّل التبويب برمجيًّا.
/// الحساب (ProfileView) مش تبويب — نوصله من زر الأفاتار بالرئيسية.
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

/// شريط آبل مخفي ومستبدل بشريط ساندي الزجاجي الطافي.
struct MainTabView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @State private var selection: MainTab = .home

    @ObservedObject private var notifs = NotificationManager.shared

    @ObservedObject private var router = DeepLinkRouter.shared
    @ObservedObject private var spotlight = SpotlightRouter.shared
    @State private var showLiveCall = false
    @State private var showQuickAdd = false

    /// لما يطلع الكيبورد نخفي شريط التبويبات والرفيق العائم حتى ما يزدحموا فوقه.
    @State private var keyboardUp = false

    var body: some View {
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
            .overlay {
                if !keyboardUp {
                    SandyCompanionLayer(tab: selection) {
                        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
                            selection = .sandy
                        }
                    }
                    .transition(.opacity)
                }
            }

            if !keyboardUp {
                FloatingTabBar(selection: $selection)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .background(SandyBackground())
        .task {
            await state.refreshOnboardingIfNeeded()
        }
        .onReceive(NotificationCenter.default.publisher(
            for: UIResponder.keyboardWillShowNotification)) { _ in
            withAnimation(.spring(response: 0.35, dampingFraction: 0.9)) { keyboardUp = true }
        }
        .onReceive(NotificationCenter.default.publisher(
            for: UIResponder.keyboardWillHideNotification)) { _ in
            withAnimation(.spring(response: 0.35, dampingFraction: 0.9)) { keyboardUp = false }
        }
        .sheet(item: $notifs.pendingRoute) { route in
            NavigationStack { routeView(route) }
                .background(SandyBackground())
                .environmentObject(state)
                .environmentObject(lang)
                .environment(\.layoutDirection, lang.lang.layoutDirection)
                .environment(\.locale, AppLocale.locale(for: lang.lang))
        }
        // التنبيه اليومي مش ورقة: بطاقته عالرئيسية، فنبدّل للرئيسية ونصفّر المسار.
        .onChange(of: notifs.pendingRoute) { _, route in
            if route == .dailyNudge {
                selection = .home
                notifs.pendingRoute = nil
            }
        }
        // `initial` يلتقط رابطًا وصل قبل ما تنبني هالشاشة.
        .onChange(of: router.pending, initial: true) { _, link in
            guard let link else { return }
            router.pending = nil
            open(link)
        }
        .onChange(of: spotlight.pendingTab, initial: true) { _, tab in
            guard let tab else { return }
            spotlight.pendingTab = nil
            selection = tab
        }
        .sheet(isPresented: $showLiveCall) {
            LiveVoiceView()
                .environmentObject(state)
                .environmentObject(lang)
                .environment(\.layoutDirection, lang.lang.layoutDirection)
                .environment(\.locale, AppLocale.locale(for: lang.lang))
        }
        .fullScreenCover(isPresented: $showQuickAdd) {
            QuickAddSheet()
                .environmentObject(state)
                .environmentObject(lang)
        }
    }

    private func open(_ link: DeepLink) {
        switch link {
        case .chat:
            withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) { selection = .sandy }
        case .call:
            showLiveCall = true
        case .quickAdd:
            showQuickAdd = true
        }
    }

    @ViewBuilder
    private func routeView(_ route: NotifRoute) -> some View {
        switch route {
        case .reminders:  RemindersView()
        case .tasks:      TasksView()
        case .future:     FutureMessagesView()
        case .insights:   InsightsView()
        case .dailyNudge: EmptyView()
        }
    }
}

// MARK: - FloatingTabBar
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
        .liquidGlassPress()
        .accessibilityLabel(lang.s(tab.titleKey))
        // بدونها قارئ الشاشة ما بيقول أي تبويب مختار.
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }
}
