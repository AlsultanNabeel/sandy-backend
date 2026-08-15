import SwiftUI

/// مراحل التطبيق. `launching` = نحاول نستعيد الجلسة قبل ما نقرّر دخول/رئيسية.
enum Stage { case launching, auth, onboarding, chat }

@MainActor
final class AppState: ObservableObject {

    @Published var stage: Stage = .launching
    @Published var baseURL: String {
        didSet {
            api.baseURL = baseURL
            UserDefaults.standard.set(baseURL, forKey: Backend.urlDefaultsKey)
        }
    }
    /// بيانات التعارف (الاسم المفضّل + الاهتمامات) — تُعرض بتبويب حسابي.
    @Published var onboarding = OnboardingData()
    /// الميزات اللي أخفاها المالك مركزياً (طبقة السيرفر) — كل شبكة تبويب تحترمها.
    @Published var serverHiddenFeatures: Set<String> = []
    let api: APIClient
    /// حالة الاشتراك + الشراء (RevenueCat عند توفّره، وحالة الباك-إند دائمًا).
    let subscriptions = SubscriptionManager()

    init() {
        // عنوان الخادم المحفوظ (لو غيّره المستخدم) وإلا الافتراضي. التعيين بالـinit
        // ما يشغّل didSet فما في حفظ زائد.
        let saved = Backend.currentURL
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
            setupPush()
        } catch {
            api.token = nil
            stage = .auth
        }
    }

    /// After a successful sign-in, go to onboarding (first time) or chat.
    func routeAfterAuth(onboardingDone: Bool) {
        stage = onboardingDone ? .chat : .onboarding
        setupPush()
    }

    /// بعد أي دخول ناجح: نطلب إذن الإشعارات ونربط رفع توكن جهاز APNs للباك-إند
    /// (الطلبان مُصادَقان فلازم يجوا بعد ما يجهز التوكن). idempotent وآمن للتكرار.
    private func setupPush() {
        NotificationManager.shared.bindDeviceToken { [weak self] deviceToken in
            guard let self else { return }
            Task { try? await self.api.registerPushToken(deviceToken) }
        }
        NotificationManager.shared.requestAuthorization()

        // الاشتراك: نعرّف RevenueCat بهوية المستخدم (لو الحزمة+المفتاح جاهزين)
        // ونعكس حالة الباك-إند. حميد بدونهما — يبقى المستخدم مجّاني.
        subscriptions.configure(userId: api.currentUserId)
        Task { await subscriptions.refresh(api: api) }

        // طبقة السيرفر لإخفاء الميزات (يضبطها المالك من هيروكو).
        Task { serverHiddenFeatures = (try? await api.getFeatures()) ?? [] }
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
    /// نلغي توكن دفع هالجهاز أولاً (بينما التوكن لسّا صالح) حتى ما يوصله دفع
    /// المستخدم القديم — أفضل جهد، والباك-إند بينظّف التوكن الميت تلقائيًا كمان.
    func signOut() {
        if let deviceToken = NotificationManager.shared.lastDeviceToken {
            let apiRef = api
            Task { try? await apiRef.unregisterPushToken(deviceToken) }
        }
        NotificationManager.shared.onDeviceToken = nil
        api.token = nil
        onboarding = OnboardingData()
        stage = .auth
    }
}
