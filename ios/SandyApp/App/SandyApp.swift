import CoreSpotlight
import OSLog
import SwiftUI
import UIKit
#if canImport(GoogleSignIn)
import GoogleSignIn
#endif

/// بس لمسك توكن جهاز APNs وتمريره لـ NotificationManager.
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
        Logger(subsystem: Bundle.main.bundleIdentifier ?? "SandyApp", category: "push")
            .error("APNs registration failed: \(error.localizedDescription, privacy: .public)")
    }
}

@main
struct SandyApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var state = AppState()
    @StateObject private var lang = LanguageManager.shared

    init() { Guidance.configure() }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(state)
                .environmentObject(lang)
                .environment(\.layoutDirection, lang.lang.layoutDirection)
                .environment(\.locale, AppLocale.locale(for: lang.lang))
                // Text size, element size and light / dark from Profile › Display.
                .sandyDisplay()
                .onOpenURL { url in
                    if DeepLinkRouter.shared.handle(url) { return }
                    #if canImport(GoogleSignIn)
                    GIDSignIn.sharedInstance.handle(url)
                    #endif
                }
                .onContinueUserActivity(CSSearchableItemActionType) { activity in
                    SpotlightRouter.shared.handle(activity)
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
        // Launch-screen mark fades out over the already-rendered app; never blocks touches.
        .overlay {
            if !handoffDone {
                LaunchHandoff { handoffDone = true }
            }
        }
        .task {
            if state.needsSessionRestore { await state.restoreSession() }
        }
        // زر مركز التحكم بيترك الرابط بالمساحة المشتركة احتياطًا.
        .onChange(of: scenePhase, initial: true) { _, phase in
            // Leaving the front ends an undo offer as kept: its delete goes out now.
            guard phase == .active else { UndoCenter.shared.commitNow(); return }
            DeepLinkRouter.shared.consumeSharedPending()
            // Settings may have changed while away: the permission cards follow.
            Task { await Permissions.shared.refresh() }
            // Changes made offline go out as soon as the app is back in front.
            if state.stage == .chat { Task { await Outbox.shared.drain(state.api) } }
        }
    }
}

/// Continues the system launch screen (Info.plist `UILaunchScreen`) seamlessly, then fades it.
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
            withAnimation(Animation.easeOut(duration: 0.42).reduced) { leaving = true }
            try? await Task.sleep(nanoseconds: 450_000_000)
            onFinished()
        }
    }
}

/// تتفادى وميض شاشة الدخول أثناء استعادة الجلسة.
struct LaunchView: View {
    var body: some View {
        ZStack {
            SandyBackground()
            VStack(spacing: Theme.Spacing.lg) {
                SandyRobot(size: 96, happy: true, animated: true)
                LoadingDots()
            }
        }
    }
}
