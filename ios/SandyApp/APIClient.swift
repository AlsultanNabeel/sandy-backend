import Foundation

/// Talks to the Sandy backend (the Python API we built).
final class APIClient {
    var baseURL: String
    var token: String?

    init(baseURL: String) { self.baseURL = baseURL }

    private func request(_ path: String,
                         method: String = "GET",
                         body: [String: Any]? = nil,
                         auth: Bool = true) async throws -> [String: Any] {
        guard let url = URL(string: baseURL + path) else { throw APIError(message: "عنوان غير صالح") }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if auth, let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        if let body { req.httpBody = try JSONSerialization.data(withJSONObject: body) }

        let (data, resp) = try await URLSession.shared.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        if code >= 400 { throw APIError(message: (json["error"] as? String) ?? "خطأ \(code)") }
        return json
    }

    // دخول المطوّر السريع (كلمة سر المالك) — للتجربة.
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

    func sendMessage(_ text: String) async throws -> String {
        let r = try await request("/api/agent", method: "POST",
                                  body: ["message": text, "lang": "ar"])
        return r["reply"] as? String ?? "…"
    }
}
