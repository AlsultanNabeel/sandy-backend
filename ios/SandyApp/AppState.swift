import SwiftUI

enum Stage { case auth, onboarding, chat }

@MainActor
final class AppState: ObservableObject {
    @Published var stage: Stage = .auth
    @Published var baseURL: String = "http://localhost:8080" {
        didSet { api.baseURL = baseURL }
    }
    /// بيانات التعارف (الاسم المفضّل + الاهتمامات) — تُعرض بتبويب حسابي.
    @Published var onboarding = OnboardingData()
    let api = APIClient(baseURL: "http://localhost:8080")

    /// After a successful sign-in, go to onboarding (first time) or chat.
    func routeAfterAuth(onboardingDone: Bool) {
        stage = onboardingDone ? .chat : .onboarding
    }

    /// يجيب بيانات التعارف ويخزّنها (لتبويب حسابي). يتجاهل الأخطاء بصمت.
    func refreshOnboarding() async {
        if let data = try? await api.getOnboarding() {
            onboarding = data
        }
    }

    /// يحفظ الاسم المفضّل + الاهتمامات بالباك-إند ويعكسها محلياً.
    func saveProfile(preferredName: String, interests: [String]) async throws {
        try await api.saveOnboarding(preferredName: preferredName, interests: interests)
        onboarding.preferredName = preferredName
        onboarding.interests = interests
    }

    /// تسجيل خروج: يمسح التوكن ويرجّع لشاشة الدخول.
    func signOut() {
        api.token = nil
        onboarding = OnboardingData()
        stage = .auth
    }
}
