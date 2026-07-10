import Foundation

extension APIClient {
    func devLogin(password: String) async throws {
        let r = try await request("/api/auth", method: "POST",
                                  body: ["password": password], auth: false)
        guard let t = r["token"] as? String else { throw APIError(message: "ما رجع توكن") }
        token = t
    }

    // تسجيل دخول آبل — يرجّع هل التعارف خلص.
    func signInApple(idToken: String, name: String) async throws -> Bool {
        let r = try await request("/api/auth/apple", method: "POST",
                                  body: ["id_token": idToken, "name": name], auth: false)
        guard let t = r["token"] as? String else { throw APIError(message: "فشل التحقّق") }
        token = t
        return r["onboarding_done"] as? Bool ?? false
    }

    // تسجيل دخول جوجل — نمرّر id token من حزمة GoogleSignIn، يرجّع هل التعارف خلص.
    func signInGoogle(idToken: String) async throws -> Bool {
        let r = try await request("/api/auth/google", method: "POST",
                                  body: ["id_token": idToken], auth: false)
        guard let t = r["token"] as? String else { throw APIError(message: "فشل التحقّق من جوجل") }
        token = t
        return r["onboarding_done"] as? Bool ?? false
    }

    // إنشاء حساب بالإيميل والباسوورد — يرجّع هل التعارف خلص.
    func signUpEmail(email: String, password: String) async throws -> Bool {
        let r = try await request("/api/auth/email/register", method: "POST",
                                  body: ["email": email, "password": password], auth: false)
        guard let t = r["token"] as? String else { throw APIError(message: "فشل إنشاء الحساب") }
        token = t
        return r["onboarding_done"] as? Bool ?? false
    }

    // تسجيل دخول بالإيميل والباسوورد — يرجّع هل التعارف خلص.
    func signInEmail(email: String, password: String) async throws -> Bool {
        let r = try await request("/api/auth/email/login", method: "POST",
                                  body: ["email": email, "password": password], auth: false)
        guard let t = r["token"] as? String else { throw APIError(message: "بيانات الدخول غلط") }
        token = t
        return r["onboarding_done"] as? Bool ?? false
    }

    // ── التنبيه اليومي + الدفع (المرحلة السابعة) ─────────────────────────────

    // GET /api/daily-nudge → {kind:"question",qid,text} | {kind:"agenda",text} | {kind:"none"}
    func getDailyNudge() async throws -> DailyNudge {
        let r = try await request("/api/daily-nudge")
        let kind = DailyNudge.Kind(rawValue: r["kind"] as? String ?? "none") ?? .none
        return DailyNudge(kind: kind,
                          qid: r["qid"] as? String ?? "",
                          text: r["text"] as? String ?? "")
    }

    // POST /api/daily-nudge/answer {qid,answer} → {ok:true}
    func answerDailyNudge(qid: String, answer: String) async throws {
        _ = try await request("/api/daily-nudge/answer", method: "POST",
                              body: ["qid": qid, "answer": answer])
    }

    // POST /api/push/register {token,platform} — نربط توكن جهاز APNs بالمستخدم
    // حتى يقدر الباك-إند يبعتله الدفع البعيد. آمن للنداء المتكرّر (upsert).
    func registerPushToken(_ token: String) async throws {
        _ = try await request("/api/push/register", method: "POST",
                              body: ["token": token, "platform": "ios"])
    }

    // POST /api/push/unregister {token} — عند تسجيل الخروج نلغي توكن هالجهاز.
    func unregisterPushToken(_ token: String) async throws {
        _ = try await request("/api/push/unregister", method: "POST",
                              body: ["token": token])
    }

    // GET /api/features → {hidden:[...]} — الميزات اللي أخفاها المالك مركزياً.
    func getFeatures() async throws -> Set<String> {
        let r = try await request("/api/features")
        return Set((r["hidden"] as? [String]) ?? [])
    }

    // GET /api/subscription → {status,plan,is_subscriber}
    func getSubscription() async throws -> SubscriptionStatus {
        let r = try await request("/api/subscription")
        return SubscriptionStatus(status: r["status"] as? String ?? "none",
                                  plan: r["plan"] as? String ?? "",
                                  isSubscriber: r["is_subscriber"] as? Bool ?? false)
    }

    func getOnboarding() async throws -> OnboardingData {
        let r = try await request("/api/onboarding")
        return OnboardingData(done: r["done"] as? Bool ?? false,
                              preferredName: r["preferred_name"] as? String ?? "",
                              interests: r["interests"] as? [String] ?? [],
                              name: r["name"] as? String ?? "")
    }

    func saveOnboarding(preferredName: String, interests: [String]) async throws {
        _ = try await request("/api/onboarding", method: "POST",
                              body: ["preferred_name": preferredName, "interests": interests])
    }

    func getPersona() async throws -> PersonaData {
        let r = try await request("/api/persona")
        let dialects = (r["dialects"] as? [[String: Any]] ?? []).map {
            DialectOption(key: $0["key"] as? String ?? "", label: $0["label"] as? String ?? "")
        }
        return PersonaData(dialect: r["dialect"] as? String ?? "palestinian",
                           customInstructions: r["custom_instructions"] as? String ?? "",
                           availableDialects: dialects)
    }

    /// يحفظ اللهجة و/أو التعليمات المخصّصة. تعليمات فاضية = رجوع للشخصية الافتراضية.
    func savePersona(dialect: String, customInstructions: String) async throws {
        _ = try await request("/api/persona", method: "POST",
                              body: ["dialect": dialect, "custom_instructions": customInstructions])
    }
}
