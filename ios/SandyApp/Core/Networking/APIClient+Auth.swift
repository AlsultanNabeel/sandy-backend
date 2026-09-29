import Foundation

/// رد نقاط المصادقة: توكن الجلسة + هل خلص التعارف.
private struct AuthResponse: Decodable {
    let token: String?
    let onboardingDone: Bool?

    enum CodingKeys: String, CodingKey {
        case token
        case onboardingDone = "onboarding_done"
    }
}

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

private struct SubscriptionResponse: Decodable {
    let status: String?
    let plan: String?
    let isSubscriber: Bool?

    enum CodingKeys: String, CodingKey {
        case status, plan
        case isSubscriber = "is_subscriber"
    }
}

private struct DailyNudgeResponse: Decodable {
    let kind: String?
    let qid: String?
    let text: String?
}

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

private struct OnboardingSaveBody: Encodable {
    let preferredName: String
    let interests: [String]

    enum CodingKeys: String, CodingKey {
        case interests
        case preferredName = "preferred_name"
    }
}

private struct FeaturesResponse: Decodable {
    let hidden: [String]?
}

extension APIClient {
    // لا `devLogin`: كل طرق الدخول (أبل، جوجل، إيميل) بتعطي حسابًا حقيقيًا.

    func signInApple(idToken: String, name: String) async throws -> Bool {
        let r: AuthResponse = try await fetch("/api/auth/apple", method: "POST",
                                              body: ["id_token": idToken, "name": name], auth: false)
        guard let t = r.token else { throw APIError(message: "فشل التحقّق") }
        token = t
        return r.onboardingDone ?? false
    }

    func signInGoogle(idToken: String) async throws -> Bool {
        let r: AuthResponse = try await fetch("/api/auth/google", method: "POST",
                                              body: ["id_token": idToken], auth: false)
        guard let t = r.token else { throw APIError(message: "فشل التحقّق من جوجل") }
        token = t
        return r.onboardingDone ?? false
    }

    func signUpEmail(email: String, password: String) async throws -> Bool {
        let r: AuthResponse = try await fetch("/api/auth/email/register", method: "POST",
                                              body: ["email": email, "password": password], auth: false)
        guard let t = r.token else { throw APIError(message: "فشل إنشاء الحساب") }
        token = t
        return r.onboardingDone ?? false
    }

    func signInEmail(email: String, password: String) async throws -> Bool {
        let r: AuthResponse = try await fetch("/api/auth/email/login", method: "POST",
                                              body: ["email": email, "password": password], auth: false)
        guard let t = r.token else { throw APIError(message: "بيانات الدخول غلط") }
        token = t
        return r.onboardingDone ?? false
    }

    // ── التنبيه اليومي + الدفع ──

    func getDailyNudge() async throws -> DailyNudge {
        let r: DailyNudgeResponse = try await fetch("/api/daily-nudge")
        let kind = DailyNudge.Kind(rawValue: r.kind ?? "none") ?? .none
        return DailyNudge(kind: kind,
                          qid: r.qid ?? "",
                          text: r.text ?? "")
    }

    func answerDailyNudge(qid: String, answer: String) async throws {
        try await send("/api/daily-nudge/answer", method: "POST",
                       body: ["qid": qid, "answer": answer])
    }

    // آمن للنداء المتكرّر (upsert).
    func registerPushToken(_ token: String) async throws {
        try await send("/api/push/register", method: "POST",
                       body: ["token": token, "platform": "ios"])
    }

    /// `bearer`: sign-out passes the token it is about to clear.
    func unregisterPushToken(_ token: String, bearer: String? = nil) async throws {
        try await send("/api/push/unregister", method: "POST",
                       body: ["token": token], bearer: bearer)
    }

    func getFeatures() async throws -> Set<String> {
        let r: FeaturesResponse = try await fetch("/api/features")
        return Set(r.hidden ?? [])
    }

    func getSubscription() async throws -> SubscriptionStatus {
        let r: SubscriptionResponse = try await fetch("/api/subscription")
        return SubscriptionStatus(status: r.status ?? "none",
                                  plan: r.plan ?? "",
                                  isSubscriber: r.isSubscriber ?? false)
    }

    /// مهلة قصيرة لأن الإقلاع مستنّي هالطلب؛ مع إعادتين أقصاها حوالي ٢٥ ثانية.
    func getOnboarding() async throws -> OnboardingData {
        let r: OnboardingResponse = try await fetch("/api/onboarding", timeout: 8)
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

    /// تعليمات فاضية = رجوع للشخصية الافتراضية.
    func savePersona(dialect: String, customInstructions: String) async throws {
        try await send("/api/persona", method: "POST",
                       body: ["dialect": dialect, "custom_instructions": customInstructions])
    }
}
