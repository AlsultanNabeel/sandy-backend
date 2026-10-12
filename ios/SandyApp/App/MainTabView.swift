import StoreKit
import SwiftUI
import TipKit

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
    /// Tabs with a screen pushed over their root. Tapping such a tab's button takes it
    /// back to its root, as «back» all the way would.
    @State private var deep: Set<MainTab> = []
    /// Bumped to rebuild a tab's stack at its root: its pushes are `NavigationLink`s with
    /// destinations, which no path binding can pop.
    @State private var resets: [MainTab: Int] = [:]

    @ObservedObject private var notifs = NotificationManager.shared

    @ObservedObject private var router = DeepLinkRouter.shared
    @ObservedObject private var spotlight = SpotlightRouter.shared
    @State private var showLiveCall = false
    @ObservedObject private var call = GeminiLiveManager.shared
    @ObservedObject private var review = ReviewPrompter.shared
    @Environment(\.requestReview) private var requestReview

    /// لما يطلع الكيبورد نخفي شريط التبويبات حتى ما يزاحمه.
    @State private var keyboardUp = false

    var body: some View {
        VStack(spacing: 0) {
            TabView(selection: $selection) {
                stack(.today) { TodayView() }
                stack(.sandy) { SandyHubView() }
                stack(.life) { LifeView() }
            }
            // Above the tab bar and clear of a list's add field.
            .undoOverlay(bottom: 72)
            .noticeOverlay()

            if call.inCall && !showLiveCall {
                CallBar(live: call) { showLiveCall = true }
                    .padding(.bottom, 6)
            }
            if !keyboardUp {
                FloatingTabBar(selection: selection, select: select)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .background(SandyBackground())
        .task {
            await state.refreshOnboardingIfNeeded()
        }
        .animation(Animation.spring(response: 0.4, dampingFraction: 0.85).reduced, value: call.inCall)
        // A good moment came (tasks finished, a week of conversations): ask, a beat later.
        .onChange(of: review.askNow) { _, ask in
            guard ask else { return }
            review.askNow = false
            Task {
                try? await Task.sleep(for: .seconds(1.5))
                requestReview()
            }
        }
        // «إنهاء» من الـ Live Activity / الجزيرة الديناميكية (sandy://call/end), screen open or not.
        .onReceive(DeepLinkRouter.shared.endCall) { _ in
            call.stop()
            showLiveCall = false
        }
        .onReceive(NotificationCenter.default.publisher(
            for: UIResponder.keyboardWillShowNotification)) { _ in
            withAnimation(Animation.spring(response: 0.35, dampingFraction: 0.9).reduced) { keyboardUp = true }
        }
        .onReceive(NotificationCenter.default.publisher(
            for: UIResponder.keyboardWillHideNotification)) { _ in
            withAnimation(Animation.spring(response: 0.35, dampingFraction: 0.9).reduced) { keyboardUp = false }
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
        .onChange(of: router.pending, initial: true) { _, waiting in
            guard waiting != nil, let link = router.take() else { return }
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

    /// One tab's stack. Its root leaving the screen while its tab is the one shown means
    /// a screen was pushed over it; a tab switch hides it with the selection already moved.
    private func stack<Root: View>(_ tab: MainTab, @ViewBuilder root: () -> Root) -> some View {
        NavigationStack {
            root()
                .onAppear { deep.remove(tab) }
                .onDisappear { if selection == tab { deep.insert(tab) } }
        }
        .id(resets[tab, default: 0])
        .toolbar(.hidden, for: .tabBar)
        .tag(tab)
    }

    /// A tab bar button: shows the tab, at its root.
    private func select(_ tab: MainTab) {
        if deep.remove(tab) != nil { resets[tab, default: 0] += 1 }
        withAnimation(Animation.spring(response: 0.4, dampingFraction: 0.78).reduced) { selection = tab }
    }

    private func open(_ link: DeepLink) {
        switch link {
        case .chat:
            withAnimation(Animation.spring(response: 0.4, dampingFraction: 0.85).reduced) { selection = .sandy }
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
    let selection: MainTab
    /// Shows a tab at its root.
    let select: (MainTab) -> Void
    @EnvironmentObject var lang: LanguageManager

    /// Today and My Life on the sides; Sandy is the orb in the middle. Tap talks to her in
    /// chat, a long press calls her.
    var body: some View {
        HStack(spacing: 0) {
            sideButton(.today)
            SandyOrb(selected: selection == .sandy) {
                select(.sandy)
            } onHold: {
                DeepLinkRouter.shared.ask(.call)
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
        // The bar keeps its shape at the largest sizes, like the system's.
        .dynamicTypeSize(...DynamicTypeSize.xxLarge)
    }

    private func sideButton(_ tab: MainTab) -> some View {
        let selected = selection == tab
        return Button {
            select(tab)
        } label: {
            VStack(spacing: 3) {
                Image(systemName: tab.icon).scaledFont(19, weight: .semibold)
                Text(lang.s(tab.titleKey)).scaledFont(11, weight: .semibold, design: .rounded)
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
            // Glass from the theme's surfaces (dark or light); the robot's face carries its own
            // dark screen, so it reads on either, and the light is in the ring and the glow.
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
            // Found it: the hint never shows again.
            OrbCallTip().invalidate(reason: .actionPerformed)
            onHold()
        }
        .popoverTip(OrbCallTip(), arrowEdge: .bottom)
        .onAppear {
            withAnimation(Animation.easeInOut(duration: 2.4).repeatForever(autoreverses: true).reduced) { breathe = true }
        }
        .accessibilityLabel(lang.s("tabs.sandy"))
        .accessibilityHint(lang.s("today.holdToTalk"))
        .accessibilityAddTraits(.isButton)
    }
}
