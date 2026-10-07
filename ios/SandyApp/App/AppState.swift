import SwiftUI

/// `launching` = نحاول نستعيد الجلسة قبل ما نقرّر دخول/رئيسية.
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
    @Published var onboarding = OnboardingData()
    /// Moves when «reset my data» worked: the main screen is built again, its stores fresh.
    @Published private(set) var dataEpoch = 0
    /// الإقلاع بيجيب بيانات التعارف أصلًا، فالتبويبات ما لازم تعيد الطلب.
    private var onboardingLoaded = false
    /// الميزات اللي أخفاها المالك من السيرفر.
    @Published var serverHiddenFeatures: Set<String> = []
    let api: APIClient
    let subscriptions = SubscriptionManager()

    init() {
        let saved = Backend.currentURL
        baseURL = saved
        api = APIClient(baseURL: saved)
        // 401 → شاشة الدخول. القفزة لـ @MainActor لأن request ممكن يرجع خارج الخيط الرئيسي.
        api.onUnauthorized = { [weak self] in
            Task { @MainActor in
                // A delete still offered for «تراجع» goes into this account's outbox first.
                await UndoCenter.shared.commitBeforeSignOut()
                self?.signOut(keepingUnsent: true)
            }
        }
        // Pick the first screen before the first frame so a known user skips the launch screen.
        if api.token != nil && onboardingDoneCached {
            stage = .chat
            launchedFromCache = true
        }
    }

    /// `restoreSession` still has to run once for push setup and the background check.
    private var launchedFromCache = false

    private var verifyTask: Task<Void, Never>?

    var needsSessionRestore: Bool { stage == .launching || launchedFromCache }

    /// توكن غير صالح → نمسحه ونرجّع لشاشة الدخول (fail closed).
    func restoreSession() async {
        launchedFromCache = false
        guard api.token != nil else { stage = .auth; return }

        // Don't block launch on a server round trip; verify in the background instead.
        if onboardingDoneCached {
            stage = .chat
            setupPush()
            verifyTask?.cancel()
            verifyTask = Task { [weak self, generation = AccountSession.generation] in
                guard let self else { return }
                await self.verifySessionInBackground(generation: generation)
            }
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
            // Offline or server restart is not a dead session: keep the token.
            stage = .chat
            setupPush()
        } catch {
            api.token = nil
            stage = .auth
        }
    }

    /// The user may switch accounts while this is in flight; a late 401 or
    /// `done: false` must not hit the new account, hence the generation check.
    private func verifySessionInBackground(generation: Int) async {
        do {
            let ob = try await api.getOnboarding()
            guard generation == AccountSession.generation else { return }
            onboarding = ob
            onboardingLoaded = true
            onboardingDoneCached = ob.done
            if !ob.done { stage = .onboarding }
        } catch let error as APIError where error.kind == .unauthorized {
            guard generation == AccountSession.generation else { return }
            signOut(keepingUnsent: true)
        } catch {
            // Offline or a slow server: stay where we are.
        }
    }

    /// Stored per user id so another account on the same phone never inherits it.
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

    func routeAfterAuth(onboardingDone: Bool) {
        AccountSession.next()
        verifyTask?.cancel()
        verifyTask = nil
        onboardingDoneCached = onboardingDone
        stage = onboardingDone ? .chat : .onboarding
        setupPush()
    }

    /// لازم يجي بعد ما يجهز التوكن لأن الطلبات مُصادَقة. آمن للتكرار.
    private func setupPush() {
        NotificationManager.shared.sessionBegan()
        NotificationManager.shared.bindDeviceToken { [weak self] deviceToken in
            guard let self else { return }
            Task { try? await self.api.registerPushToken(deviceToken) }
        }
        NotificationManager.shared.requestAuthorization()

        let apiRef = api
        Task { await NotificationPrefs.pull(api: apiRef) }

        subscriptions.configure(userId: api.currentUserId)
        Task { await subscriptions.refresh(api: api) }

        Task { serverHiddenFeatures = (try? await api.getFeatures()) ?? [] }
    }

    func refreshOnboarding() async {
        if let data = try? await api.getOnboarding() {
            onboarding = data
            onboardingLoaded = true
            onboardingDoneCached = data.done
        }
    }

    func refreshOnboardingIfNeeded() async {
        guard !onboardingLoaded else { return }
        await refreshOnboarding()
    }

    func saveProfile(preferredName: String, interests: [String]) async throws {
        try await api.saveOnboarding(preferredName: preferredName, interests: interests)
        onboarding.preferredName = preferredName
        onboarding.interests = interests
    }

    /// Sends a delete still offered for «تراجع» (briefly, never held up by no network) and
    /// what waits in the outbox; true when nothing is left, so a sign-out the user chose
    /// loses nothing (else they are warned first).
    func sendUnsent() async -> Bool {
        await UndoCenter.shared.commitBeforeSignOut()
        await Outbox.shared.retryParked(api)
        return !Outbox.shared.hasUnsent
    }

    /// «Reset my data» worked on the server: the phone forgets the account's data too (the
    /// local part of a sign-out, the unsent changes dropped before the reset), still signed
    /// in, and the screens start over from the server.
    func resetLocalData() {
        clearLocal()
        NotificationManager.shared.sessionBegan()
        let apiRef = api
        Task { await NotificationPrefs.pull(api: apiRef) }
        dataEpoch &+= 1
    }

    /// What sign-out and «reset my data» both clear on the phone. Widgets and scheduled
    /// notifications don't check the session, so they go too.
    private func clearLocal() {
        AccountSession.next()
        DiskCache.clearAll(except: Outbox.fileKey, Outbox.parkedKey)
        SessionReset.clearShared()
        SpotlightIndexer.deleteAll()
        NotificationManager.shared.clearForSignOut()
        WidgetData.clearAll()
    }

    /// نلغي توكن الدفع أولاً (والتوكن لسّا صالح) حتى ما يوصل هالجهاز دفع المستخدم القديم.
    /// `keepingUnsent`: the session ended on its own (a 401), so the outbox stays for this
    /// account's return (on disk, and loaded only for it); a sign-out the user chose (after
    /// the warning) drops it.
    func signOut(keepingUnsent: Bool = false) {
        if let deviceToken = NotificationManager.shared.lastDeviceToken,
           let session = api.token {
            let apiRef = api
            Task { try? await apiRef.unregisterPushToken(deviceToken, bearer: session) }
        }
        verifyTask?.cancel()
        verifyTask = nil

        if !keepingUnsent { Outbox.shared.discard() }
        clearLocal()
        api.token = nil
        subscriptions.signOut()

        onboarding = OnboardingData()
        onboardingLoaded = false
        onboardingDoneCached = false
        stage = .auth
    }
}
