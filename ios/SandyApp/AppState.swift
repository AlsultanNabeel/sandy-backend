import SwiftUI

/// مراحل التطبيق. `launching` = نحاول نستعيد الجلسة قبل ما نقرّر دخول/رئيسية.
enum Stage { case launching, auth, onboarding, chat }

@MainActor
final class AppState: ObservableObject {
    private static let defaultBaseURL = "https://sandy-robot-3da0693d32f7.herokuapp.com"
    private static let baseURLKey = "sandy_base_url"

    @Published var stage: Stage = .launching
    @Published var baseURL: String {
        didSet {
            api.baseURL = baseURL
            UserDefaults.standard.set(baseURL, forKey: Self.baseURLKey)
        }
    }
    /// بيانات التعارف (الاسم المفضّل + الاهتمامات) — تُعرض بتبويب حسابي.
    @Published var onboarding = OnboardingData()
    let api: APIClient

    init() {
        // عنوان الخادم المحفوظ (لو غيّره المستخدم) وإلا الافتراضي. التعيين بالـinit
        // ما يشغّل didSet فما في حفظ زائد.
        let saved = UserDefaults.standard.string(forKey: Self.baseURLKey) ?? Self.defaultBaseURL
        baseURL = saved
        api = APIClient(baseURL: saved)   // التوكن يتحمّل من الـKeychain جوّا APIClient
        // 401 على طلب مُصادَق (جلسة منتهية أثناء الاستخدام) → ارجع لشاشة الدخول.
        // القفزة لـ @MainActor ضرورية: request قد يعمل خارج الخيط الرئيسي وsignOut
        // يلمس حالة @Published.
        api.onUnauthorized = { [weak self] in
            Task { @MainActor in self?.signOut() }
        }
    }

    /// استعادة الجلسة عند الإقلاع: لو في توكن محفوظ نتحقّق منه ونوجّه؛ وإلا دخول.
    /// توكن غير صالح/منتهٍ → نمسحه ونرجّع لشاشة الدخول (fail closed).
    func restoreSession() async {
        guard api.token != nil else { stage = .auth; return }
        do {
            let ob = try await api.getOnboarding()
            onboarding = ob
            stage = ob.done ? .chat : .onboarding
        } catch {
            api.token = nil
            stage = .auth
        }
    }

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

    /// تسجيل خروج: يمسح التوكن (ومن الـKeychain تلقائياً) ويرجّع لشاشة الدخول.
    func signOut() {
        api.token = nil
        onboarding = OnboardingData()
        stage = .auth
    }
}
