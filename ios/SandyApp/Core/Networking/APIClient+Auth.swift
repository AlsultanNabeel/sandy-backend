import Foundation

/// رد نقاط المصادقة الموحّد: توكن الجلسة + هل خلص التعارف. الحقول الزائدة
/// (role/user_id) يتجاهلها الفك تلقائياً.
private struct AuthResponse: Decodable {
    let token: String?
    let onboardingDone: Bool?

    enum CodingKeys: String, CodingKey {
        case token
        case onboardingDone = "onboarding_done"
    }
}

/// رد نقطة الشخصية: اللهجة الحالية + التعليمات المخصّصة + اللهجات المتاحة.
private struct PersonaResponse: Decodable {
    let dialect: String?
    let customInstructions: String?
    let dialects: [DialectRow]?

    struct DialectRow: Decodable {
        let key: String?
        let label: String?
    }

    enum CodingKeys: String, CodingKey {
        case dialect
        case customInstructions = "custom_instructions"
        case dialects
    }
}

/// رد نقطة الاشتراك: الحالة + الخطة + هل المستخدم مشترك.
private struct SubscriptionResponse: Decodable {
    let status: String?
    let plan: String?
    let isSubscriber: Bool?

    enum CodingKeys: String, CodingKey {
        case status, plan
        case isSubscriber = "is_subscriber"
    }
}

/// رد التنبيه اليومي: النوع + معرّف السؤال + النص.
private struct DailyNudgeResponse: Decodable {
    let kind: String?
    let qid: String?
    let text: String?
}

/// رد التعارف: هل خلص + الاسم المفضّل + الاهتمامات + الاسم.
private struct OnboardingResponse: Decodable {
    let done: Bool?
    let preferredName: String?
    let interests: [String]?
    let name: String?

    enum CodingKeys: String, CodingKey {
        case done, interests, name
        case preferredName = "preferred_name"
    }
}

/// جسم حفظ التعارف: الاسم المفضّل + الاهتمامات (قيم مختلطة → نوع مطبوع).
private struct OnboardingSaveBody: Encodable {
    let preferredName: String
    let interests: [String]

    enum CodingKeys: String, CodingKey {
        case interests
        case preferredName = "preferred_name"
    }
}

/// رد الميزات: أسماء الميزات المخفية مركزياً.
private struct FeaturesResponse: Decodable {
    let hidden: [String]?
}

extension APIClient {
    // `devLogin` انحذفت.
    //
    // كانت بتدخّلك بكلمة سر وحدة ع حساب اسمه «المالك» — حساب من متغيّر بيئة،
    // مش شخص. اشتغلت لأنه كان في مستخدم واحد، وما كانت بتتوسّع لتاني واحد:
    // كل من بيعرف الكلمة بيصير **نفس** الشخص، بنفس اليوميات ونفس بصمة الصوت.
    //
    // ثلاث طرق دخول وبس، وكلها بتعطي حسابًا حقيقيًا: أبل، جوجل، إيميل.

    // تسجيل دخول آبل — يرجّع هل التعارف خلص.
    func signInApple(idToken: String, name: String) async throws -> Bool {
        let r: AuthResponse = try await fetch("/api/auth/apple", method: "POST",
                                              body: ["id_token": idToken, "name": name], auth: false)
        guard let t = r.token else { throw APIError(message: "فشل التحقّق") }
        token = t
        return r.onboardingDone ?? false
    }

    // تسجيل دخول جوجل — نمرّر id token من حزمة GoogleSignIn، يرجّع هل التعارف خلص.
    func signInGoogle(idToken: String) async throws -> Bool {
        let r: AuthResponse = try await fetch("/api/auth/google", method: "POST",
                                              body: ["id_token": idToken], auth: false)
        guard let t = r.token else { throw APIError(message: "فشل التحقّق من جوجل") }
        token = t
        return r.onboardingDone ?? false
    }

    // إنشاء حساب بالإيميل والباسوورد — يرجّع هل التعارف خلص.
    func signUpEmail(email: String, password: String) async throws -> Bool {
        let r: AuthResponse = try await fetch("/api/auth/email/register", method: "POST",
                                              body: ["email": email, "password": password], auth: false)
        guard let t = r.token else { throw APIError(message: "فشل إنشاء الحساب") }
        token = t
        return r.onboardingDone ?? false
    }

    // تسجيل دخول بالإيميل والباسوورد — يرجّع هل التعارف خلص.
    func signInEmail(email: String, password: String) async throws -> Bool {
        let r: AuthResponse = try await fetch("/api/auth/email/login", method: "POST",
                                              body: ["email": email, "password": password], auth: false)
        guard let t = r.token else { throw APIError(message: "بيانات الدخول غلط") }
        token = t
        return r.onboardingDone ?? false
    }

    // ── التنبيه اليومي + الدفع (المرحلة السابعة) ─────────────────────────────

    // GET /api/daily-nudge → {kind:"question",qid,text} | {kind:"agenda",text} | {kind:"none"}
    func getDailyNudge() async throws -> DailyNudge {
        let r: DailyNudgeResponse = try await fetch("/api/daily-nudge")
        let kind = DailyNudge.Kind(rawValue: r.kind ?? "none") ?? .none
        return DailyNudge(kind: kind,
                          qid: r.qid ?? "",
                          text: r.text ?? "")
    }

    // POST /api/daily-nudge/answer {qid,answer} → {ok:true}
    func answerDailyNudge(qid: String, answer: String) async throws {
        try await send("/api/daily-nudge/answer", method: "POST",
                       body: ["qid": qid, "answer": answer])
    }

    // POST /api/push/register {token,platform} — نربط توكن جهاز APNs بالمستخدم
    // حتى يقدر الباك-إند يبعتله الدفع البعيد. آمن للنداء المتكرّر (upsert).
    func registerPushToken(_ token: String) async throws {
        try await send("/api/push/register", method: "POST",
                       body: ["token": token, "platform": "ios"])
    }

    // POST /api/push/unregister {token} — عند تسجيل الخروج نلغي توكن هالجهاز.
    func unregisterPushToken(_ token: String) async throws {
        try await send("/api/push/unregister", method: "POST",
                       body: ["token": token])
    }

    // GET /api/features → {hidden:[...]} — الميزات اللي أخفاها المالك مركزياً.
    func getFeatures() async throws -> Set<String> {
        let r: FeaturesResponse = try await fetch("/api/features")
        return Set(r.hidden ?? [])
    }

    // GET /api/subscription → {status,plan,is_subscriber}
    func getSubscription() async throws -> SubscriptionStatus {
        let r: SubscriptionResponse = try await fetch("/api/subscription")
        return SubscriptionStatus(status: r.status ?? "none",
                                  plan: r.plan ?? "",
                                  isSubscriber: r.isSubscriber ?? false)
    }

    func getOnboarding() async throws -> OnboardingData {
        let r: OnboardingResponse = try await fetch("/api/onboarding")
        return OnboardingData(done: r.done ?? false,
                              preferredName: r.preferredName ?? "",
                              interests: r.interests ?? [],
                              name: r.name ?? "")
    }

    func saveOnboarding(preferredName: String, interests: [String]) async throws {
        try await send("/api/onboarding", method: "POST",
                       body: OnboardingSaveBody(preferredName: preferredName, interests: interests))
    }

    func getPersona() async throws -> PersonaData {
        let r: PersonaResponse = try await fetch("/api/persona")
        let dialects = (r.dialects ?? []).map {
            DialectOption(key: $0.key ?? "", label: $0.label ?? "")
        }
        return PersonaData(dialect: r.dialect ?? "palestinian",
                           customInstructions: r.customInstructions ?? "",
                           availableDialects: dialects)
    }

    /// يحفظ اللهجة و/أو التعليمات المخصّصة. تعليمات فاضية = رجوع للشخصية الافتراضية.
    func savePersona(dialect: String, customInstructions: String) async throws {
        try await send("/api/persona", method: "POST",
                       body: ["dialect": dialect, "custom_instructions": customInstructions])
    }
}
