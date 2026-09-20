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
    /// هل جبنا بيانات التعارف من الخادم بهالجلسة؟ الإقلاع بيجيبها أصلًا، فالتبويبات
    /// ما لازم تعيد نفس الطلب أول ما تظهر.
    private var onboardingLoaded = false
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
        // Decide the first screen before the first frame: a signed-in user who
        // finished onboarding opens on the app itself, not on the launch screen
        // for a moment. `restoreSession` finishes the job (push, background check).
        if api.token != nil && onboardingDoneCached {
            stage = .chat
            launchedFromCache = true
        }
    }

    /// The first screen was chosen from the cache in `init`; `restoreSession`
    /// still has to run once for push setup and the background check.
    private var launchedFromCache = false

    /// Whether the launch still owes a `restoreSession` call.
    var needsSessionRestore: Bool { stage == .launching || launchedFromCache }

    /// استعادة الجلسة عند الإقلاع: لو في توكن محفوظ نتحقّق منه ونوجّه؛ وإلا دخول.
    /// توكن غير صالح/منتهٍ → نمسحه ونرجّع لشاشة الدخول (fail closed).
    func restoreSession() async {
        launchedFromCache = false
        guard api.token != nil else { stage = .auth; return }

        // **Open at once when we already know the answer.** The launch used to
        // wait for GET /api/onboarding before showing anything — a full round
        // trip to the server (seconds on a cold dyno) spent on a question whose
        // answer almost never changes. A user who finished onboarding on this
        // device goes straight in; the check still runs, in the background, and
        // corrects the screen if it has to (onboarding reset, token revoked).
        if onboardingDoneCached {
            stage = .chat
            setupPush()
            Task { await verifySessionInBackground() }
            return
        }

        do {
            let ob = try await api.getOnboarding()
            onboarding = ob
            onboardingLoaded = true
            onboardingDoneCached = ob.done
            stage = ob.done ? .chat : .onboarding
            setupPush()
        } catch let error as APIError where error.kind != .unauthorized {
            // Offline, a timeout or a server restart is not a dead session:
            // keep the token instead of forcing a fresh sign-in.
            stage = .chat
            setupPush()
        } catch {
            api.token = nil
            stage = .auth
        }
    }

    /// The background half of a cached launch: same answers as the blocking
    /// path, applied after the first frame instead of before it.
    private func verifySessionInBackground() async {
        do {
            let ob = try await api.getOnboarding()
            onboarding = ob
            onboardingLoaded = true
            onboardingDoneCached = ob.done
            if !ob.done { stage = .onboarding }
        } catch let error as APIError where error.kind == .unauthorized {
            signOut()
        } catch {
            // Offline or a slow server: stay where we are, like the blocking path.
        }
    }

    /// "This user finished onboarding" — remembered per account on this device,
    /// so a different account on the same phone never inherits it.
    private static let onboardingDoneKey = "sandy_onboarding_done_for"
    var onboardingDoneCached: Bool {
        get {
            guard let uid = api.currentUserId else { return false }
            return UserDefaults.standard.string(forKey: Self.onboardingDoneKey) == uid
        }
        set {
            if newValue, let uid = api.currentUserId {
                UserDefaults.standard.set(uid, forKey: Self.onboardingDoneKey)
            } else {
                UserDefaults.standard.removeObject(forKey: Self.onboardingDoneKey)
            }
        }
    }

    /// After a successful sign-in, go to onboarding (first time) or chat.
    func routeAfterAuth(onboardingDone: Bool) {
        onboardingDoneCached = onboardingDone
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
            onboardingLoaded = true
            onboardingDoneCached = data.done
        }
    }

    /// زي `refreshOnboarding` بس بتتخطّى الطلب لو البيانات انجابت بهالجلسة.
    func refreshOnboardingIfNeeded() async {
        guard !onboardingLoaded else { return }
        await refreshOnboarding()
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
        if let deviceToken = NotificationManager.shared.lastDeviceToken,
           let session = api.token {
            let apiRef = api
            Task { try? await apiRef.unregisterPushToken(deviceToken, bearer: session) }
        }
        NotificationManager.shared.onDeviceToken = nil
        api.token = nil
        // النسخ المحلية بتروح مع الحساب: مخزن بدون إنترنت وفهرس البحث.
        DiskCache.clearAll()
        SpotlightIndexer.deleteAll()
        onboarding = OnboardingData()
        onboardingLoaded = false
        onboardingDoneCached = false
        stage = .auth
    }
}
