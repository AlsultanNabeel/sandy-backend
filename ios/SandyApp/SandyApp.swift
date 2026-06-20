import SwiftUI

@main
struct SandyApp: App {
    @StateObject private var state = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(state)
                .environment(\.layoutDirection, .rightToLeft) // واجهة عربية
        }
    }
}

struct RootView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        switch state.stage {
        case .auth:        AuthView()
        case .onboarding:  OnboardingView()
        case .chat:        ChatView()
        }
    }
}
