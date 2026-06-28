import SwiftUI
import GoogleSignIn

@main
struct SandyApp: App {
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
                // واجهة داكنة دائماً عشان تطابق باليت الويب الأوبسيديان + تتناسق
                // أدوات النظام (حقول النص/الأزرار بشاشة الدخول) مع الخلفية الداكنة.
                .preferredColorScheme(.dark)
                // استقبال رابط رجوع جوجل بعد المصادقة.
                .onOpenURL { GIDSignIn.sharedInstance.handle($0) }
        }
    }
}

struct RootView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        Group {
            switch state.stage {
            case .launching:   LaunchView()
            case .auth:        AuthView()
            case .onboarding:  OnboardingView()
            case .chat:        MainTabView()
            }
        }
        // نحاول استعادة الجلسة مرّة عند الإقلاع (توكن محفوظ → رئيسية مباشرة).
        .task {
            if state.stage == .launching { await state.restoreSession() }
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
