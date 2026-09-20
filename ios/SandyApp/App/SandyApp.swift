import OSLog
import SwiftUI
import UIKit
#if canImport(GoogleSignIn)
import GoogleSignIn
#endif

/// مندوب التطبيق — نحتاجه فقط لمسك توكن جهاز APNs عند التسجيل للدفع البعيد
/// ونمرّره لـ NotificationManager (اللي بدوره يرفعه للباك-إند). بدون مفاتيح آبل
/// بالسيرفر هالمسار حميد: التسجيل بينجح والتوكن بينحفظ، بس ما بيوصل دفع لحد ما
/// تُضاف المفاتيح.
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        // No call runs at launch: clear any call Live Activity a killed run left behind.
        CallLiveActivity.endStale()
        return true
    }

    func application(_ application: UIApplication,
                     didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        NotificationManager.shared.handleDeviceToken(deviceToken)
    }

    func application(_ application: UIApplication,
                     didFailToRegisterForRemoteNotificationsWithError error: Error) {
        // os.Logger مش print: بينضم لسجل النظام مع وسم وتصنيف، فبينقرا من
        // Console ع جهاز حقيقي — وprint ما بتطلع أصلًا ببناء الإصدار.
        Logger(subsystem: Bundle.main.bundleIdentifier ?? "SandyApp", category: "push")
            .error("APNs registration failed: \(error.localizedDescription, privacy: .public)")
    }
}

@main
struct SandyApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var state = AppState()
    /// مدير اللغة المشترك — يقود اتجاه الواجهة (RTL/LTR) لكل التطبيق ويزوّد الترجمة.
    @StateObject private var lang = LanguageManager.shared

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(state)
                .environmentObject(lang)
                // الاتجاه يتبع اللغة: عربي → RTL، إنجليزي → LTR (يقابل dir بالويب).
                .environment(\.layoutDirection, lang.lang.layoutDirection)
                // التواريخ/الأرقام بأدوات النظام (DatePicker، Text(date, style:)) تتبع لغة التطبيق.
                .environment(\.locale, AppLocale.locale(for: lang.lang))
                // واجهة داكنة دائماً عشان تطابق باليت الويب الأوبسيديان + تتناسق
                // أدوات النظام (حقول النص/الأزرار بشاشة الدخول) مع الخلفية الداكنة.
                .preferredColorScheme(.dark)
                // استقبال رابط رجوع جوجل بعد المصادقة.
                .onOpenURL { url in
                    // روابط ساندي (ويدجت / Live Activity / مركز التحكم) أولاً.
                    if DeepLinkRouter.shared.handle(url) { return }
                    #if canImport(GoogleSignIn)
                    GIDSignIn.sharedInstance.handle(url)
                    #endif
                }
        }
    }
}

struct RootView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.scenePhase) private var scenePhase
    @State private var handoffDone = false

    var body: some View {
        Group {
            switch state.stage {
            case .launching:   LaunchView()
            case .auth:        AuthView()
            case .onboarding:  OnboardingView()
            case .chat:        MainTabView()
            }
        }
        // The launch screen's Sandy, picked up at the exact same spot and sent
        // off: she glows, grows a little and fades while the app appears behind
        // her. It never blocks a touch and never delays the first screen — the
        // app is already there underneath.
        .overlay {
            if !handoffDone {
                LaunchHandoff { handoffDone = true }
            }
        }
        // نحاول استعادة الجلسة مرّة عند الإقلاع (توكن محفوظ → رئيسية مباشرة).
        .task {
            if state.needsSessionRestore { await state.restoreSession() }
        }
        // زر «تكلّم مع ساندي» بمركز التحكم بيترك الرابط بالمساحة المشتركة احتياطًا.
        .onChange(of: scenePhase, initial: true) { _, phase in
            if phase == .active { DeepLinkRouter.shared.consumeSharedPending() }
        }
    }
}

/// Continues the system launch screen (`UILaunchScreen` in Info.plist: the
/// `LaunchBackground` color with `LaunchMark` centred at its natural 240 pt) so
/// the hand-off from the OS to the app has no seam, then animates it away.
private struct LaunchHandoff: View {
    let onFinished: () -> Void
    @State private var leaving = false

    /// LaunchMark@3x.png is 720 px → 240 pt, the size the launch screen draws it.
    private static let markSize: CGFloat = 240

    var body: some View {
        ZStack {
            Color("LaunchBackground")
                .opacity(leaving ? 0 : 1)
            Image("LaunchMark")
                .resizable()
                .frame(width: Self.markSize, height: Self.markSize)
                .scaleEffect(leaving ? 1.18 : 1)
                .brightness(leaving ? 0.12 : 0)
                .blur(radius: leaving ? 6 : 0)
                .opacity(leaving ? 0 : 1)
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
        .accessibilityHidden(true)
        .task {
            withAnimation(.easeOut(duration: 0.42)) { leaving = true }
            try? await Task.sleep(nanoseconds: 450_000_000)
            onFinished()
        }
    }
}

/// شاشة إقلاع قصيرة أثناء استعادة الجلسة — تتفادى وميض شاشة الدخول.
struct LaunchView: View {
    var body: some View {
        ZStack {
            SandyBackground()
            VStack(spacing: Theme.Spacing.lg) {
                SandyRobot(size: 96, happy: true, animated: true)
                ProgressView().tint(Theme.Colors.accent)
            }
        }
    }
}
