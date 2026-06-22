import SwiftUI

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
        }
    }
}

struct RootView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        switch state.stage {
        case .auth:        AuthView()
        case .onboarding:  OnboardingView()
        case .chat:        MainTabView()
        }
    }
}
