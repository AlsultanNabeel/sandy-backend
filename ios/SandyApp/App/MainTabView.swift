import SwiftUI

/// الترتيب ثابت ومرتبط بـ `selection` حتى نقدر نبدّل التبويب برمجيًّا.
/// الحساب (ProfileView) مش تبويب — نوصله من زر الأفاتار بالرئيسية.
enum MainTab: Int, Hashable, CaseIterable {
    case today, sandy, life

    var icon: String {
        switch self {
        case .today: return "sun.max.fill"
        case .sandy: return "sparkles"
        case .life:  return "heart.text.square.fill"
        }
    }

    var titleKey: String {
        switch self {
        case .today: return "tabs.today"
        case .sandy: return "tabs.sandy"
        case .life:  return "tabs.life"
        }
    }
}

/// شريط آبل مخفي ومستبدل بشريط ساندي الزجاجي الطافي.
struct MainTabView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @State private var selection: MainTab = .today

    @ObservedObject private var notifs = NotificationManager.shared

    @ObservedObject private var router = DeepLinkRouter.shared
    @ObservedObject private var spotlight = SpotlightRouter.shared
    @State private var showLiveCall = false
    @ObservedObject private var call = GeminiLiveManager.shared

    /// لما يطلع الكيبورد نخفي شريط التبويبات حتى ما يزاحمه.
    @State private var keyboardUp = false

    var body: some View {
        VStack(spacing: 0) {
            TabView(selection: $selection) {
                NavigationStack { TodayView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.today)

                NavigationStack { SandyHubView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.sandy)

                NavigationStack { LifeView() }
                    .toolbar(.hidden, for: .tabBar)
                    .tag(MainTab.life)
            }

            if call.inCall && !showLiveCall {
                CallBar(live: call) { showLiveCall = true }
                    .padding(.bottom, 6)
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
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: call.inCall)
        // «إنهاء» من الـ Live Activity / الجزيرة الديناميكية (sandy://call/end), screen open or not.
        .onReceive(DeepLinkRouter.shared.endCall) { _ in
            call.stop()
            showLiveCall = false
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
                selection = .today
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
    }

    private func open(_ link: DeepLink) {
        switch link {
        case .chat:
            withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) { selection = .sandy }
        case .call:
            showLiveCall = true
        case .quickAdd:
            // Adding anything is the ask bar on Today now.
            selection = .today
            AskBarFocus.shared.request &+= 1
        }
    }

    @ViewBuilder
    private func routeView(_ route: NotifRoute) -> some View {
        switch route {
        case .reminders:  SchedulesView()
        case .tasks:      ItemsView(kind: KindsStore.shared.kindOrBare("tasks", .list))
        case .future:     SchedulesView(kind: "message_to_future_self")
        case .insights:   LogView()
        case .dailyNudge: EmptyView()
        }
    }
}

// MARK: - FloatingTabBar
struct FloatingTabBar: View {
    @Binding var selection: MainTab
    @EnvironmentObject var lang: LanguageManager

    /// Today and My Life on the sides; Sandy is the orb in the middle. Tap talks to her in
    /// chat, a long press calls her.
    var body: some View {
        HStack(spacing: 0) {
            sideButton(.today)
            SandyOrb(selected: selection == .sandy) {
                withAnimation(.spring(response: 0.4, dampingFraction: 0.78)) { selection = .sandy }
            } onHold: {
                DeepLinkRouter.shared.pending = .call
            }
            .offset(y: -14)
            sideButton(.life)
        }
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.vertical, 6)
        .liquidGlass(cornerRadius: Theme.Radius.pill, tint: 0.08)
        .shadow(color: Theme.Shadow.liftColor,
                radius: Theme.Shadow.liftRadius, x: 0, y: Theme.Shadow.liftY)
        .padding(.horizontal, Theme.Spacing.xl)
        .padding(.bottom, Theme.Spacing.sm)
    }

    private func sideButton(_ tab: MainTab) -> some View {
        let selected = selection == tab
        return Button {
            withAnimation(.spring(response: 0.4, dampingFraction: 0.78)) { selection = tab }
        } label: {
            VStack(spacing: 3) {
                Image(systemName: tab.icon).font(.system(size: 19, weight: .semibold))
                Text(lang.s(tab.titleKey)).font(.system(size: 11, weight: .semibold, design: .rounded))
            }
            .foregroundColor(selected ? Theme.Colors.accent : Theme.Colors.secondaryText)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(lang.s(tab.titleKey))
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }
}

/// Sandy in the tab bar: a glowing orb that breathes, brighter when her tab is open.
private struct SandyOrb: View {
    @EnvironmentObject var lang: LanguageManager
    let selected: Bool
    let onTap: () -> Void
    let onHold: () -> Void
    @State private var breathe = false

    var body: some View {
        ZStack {
            Circle()
                .fill(Theme.Colors.accent.opacity(0.22))
                .frame(width: breathe ? 76 : 64, height: breathe ? 76 : 64)
                .blur(radius: 6)
            // Dark glass so the robot reads clearly; the light is in the ring and the glow.
            Circle()
                .fill(RadialGradient(colors: [Theme.Colors.surface, Theme.Colors.background],
                                     center: .topLeading, startRadius: 2, endRadius: 60))
                .frame(width: 58, height: 58)
                .overlay(Circle().strokeBorder(
                    AngularGradient(colors: [Theme.Colors.accent, Theme.Colors.accentDeep,
                                             Theme.Colors.success, Theme.Colors.accent],
                                    center: .center),
                    lineWidth: selected ? 3 : 2))
                .shadow(color: Theme.Colors.accent.opacity(selected ? 0.7 : 0.4), radius: selected ? 16 : 10)
            SandyAvatar(size: 38, mood: .happy)
        }
        .frame(width: 80)
        .contentShape(Circle())
        .onTapGesture { onTap() }
        .onLongPressGesture(minimumDuration: 0.35) {
            Haptics.play(.listening)
            onHold()
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 2.4).repeatForever(autoreverses: true)) { breathe = true }
        }
        .accessibilityLabel(lang.s("tabs.sandy"))
        .accessibilityHint(lang.s("today.holdToTalk"))
        .accessibilityAddTraits(.isButton)
    }
}
