import Foundation

/// Talks to the Sandy backend; endpoints live in the `APIClient+<Feature>` extensions.
final class APIClient: APIClientProtocol {
    /// `waitsForConnectivity` OFF on purpose: with it on, timeouts are ignored offline (endless
    /// spinner); `sendWithRetry` handles handover. Not private: the extensions send through it.
    static let session: URLSession = URLSession(configuration: .default)

    /// Retries for idempotent methods only: retrying a POST could create a task twice.
    static let idempotentMethods: Set<String> = ["GET", "HEAD"]
    static let maxRetries = 2

    var baseURL: String {
        didSet { if mirrorsShared { SharedAuth.mirror(baseURL: baseURL) } }
    }
    /// يُحفظ تلقائياً بالـKeychain المشترك (nil = خروج)، فالويدجت والمشاركة بيقروه.
    var token: String? {
        didSet { tokenStore.save(token) }
    }
    /// Where the token is kept (the shared Keychain) and whether the address is mirrored for
    /// the widget and the share extension. A test passes its own, so it never signs the app out.
    private let tokenStore: TokenStore
    private let mirrorsShared: Bool

    var onUnauthorized: (() -> Void)?

    /// مفكوكة من حمولة الـJWT بلا تحقّق — للعرض والربط فقط (مثلاً app_user_id لـRevenueCat).
    var currentUserId: String? {
        guard let t = token else { return nil }
        let parts = t.split(separator: ".")
        guard parts.count == 3 else { return nil }
        var b64 = String(parts[1]).replacingOccurrences(of: "-", with: "+")
                                   .replacingOccurrences(of: "_", with: "/")
        while b64.count % 4 != 0 { b64 += "=" }   // JWT يحذف الحشو
        guard let data = Data(base64Encoded: b64),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return obj["user_id"] as? String
    }

    init(baseURL: String, tokenStore: TokenStore = KeychainTokenStore(), mirrorsShared: Bool = true) {
        self.baseURL = baseURL
        self.tokenStore = tokenStore
        self.mirrorsShared = mirrorsShared
        // التعيين بالـinit ما يشغّل didSet.
        self.token = tokenStore.load()
        // توكن قديم قبل مجموعة الوصول المشتركة: إعادة الحفظ بتنقله للإضافات.
        if token != nil { tokenStore.save(token) }
        if mirrorsShared { SharedAuth.mirror(baseURL: baseURL) }
    }

    /// Retries only transport failures on safe methods; never cancellation or server errors.
    static func sendWithRetry(_ req: URLRequest,
                              method: String) async throws -> (Data, URLResponse) {
        var attempt = 0
        while true {
            do {
                return try await session.data(for: req)
            } catch let error as URLError {
                // `.timedOut` retries the whole timeout, so callers the user waits on pass a short one.
                let retryable: Set<URLError.Code> = [
                    .networkConnectionLost, .timedOut, .cannotConnectToHost,
                    .dnsLookupFailed, .notConnectedToInternet,
                ]
                guard idempotentMethods.contains(method),
                      retryable.contains(error.code),
                      attempt < maxRetries
                else { throw error }
                attempt += 1
                // Back off so a handover can settle. `try`, not `try?`: this sleep is the loop's
                // only cancellation checkpoint.
                try await Task.sleep(nanoseconds: UInt64(attempt) * 400_000_000)
            }
        }
    }

    // النقل الأساسي: منطق الشبكة والأخطاء مكتوب مرة واحدة هون.
    /// نداء بيرجّع البايتات زي ما هي — للردود اللي مش JSON.
    func rawPost(_ path: String, timeout: TimeInterval = 30) async throws -> Data {
        let data = try await perform(path, method: "POST",
                                     bodyData: Data("{}".utf8),
                                     auth: true, timeout: timeout)
        guard !data.isEmpty else { throw APIError(message: "رد فاضي") }
        return data
    }

    func rawGet(_ path: String, timeout: TimeInterval = 15) async throws -> Data {
        try await perform(path, method: "GET", bodyData: nil,
                          auth: true, timeout: timeout)
    }

    private func perform(_ path: String,
                         method: String,
                         bodyData: Data?,
                         auth: Bool,
                         timeout: TimeInterval = 30,
                         bearer: String? = nil) async throws -> Data {
        guard let url = URL(string: baseURL + path) else { throw APIError(message: "عنوان غير صالح") }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = timeout
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // `bearer` lets sign-out send a request after `token` is already cleared.
        let sentToken = auth ? (bearer ?? token) : nil
        if let t = sentToken { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        req.setValue(TimeZone.current.identifier, forHTTPHeaderField: "X-Timezone")
        req.httpBody = bodyData

        let data: Data
        let resp: URLResponse
        do {
            (data, resp) = try await Self.sendWithRetry(req, method: method)
        } catch let urlError as URLError {
            // Keep cancellation identity so callers can suppress it instead of showing "couldn't load".
            if urlError.code == .cancelled { throw urlError }
            // Offline, timeout or dropped connection → one "check your internet" error.
            throw APIError(message: "تعذّر الاتصال بالخادم. تأكد من الإنترنت وحاول مرة ثانية.", kind: .connection)
        }
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        let machine = Self.nonEmpty(body?["error"] as? String)
        let human = Self.nonEmpty(body?["message"] as? String)

        // 401 على طلب موثَّق = الجلسة ماتت؛ على طلب مش موثَّق = دخول فشل (رمزه يوصل لـ`friendlyAuthError`).
        if code == 401 && auth {
            // Only the current session dying signs out; a request with an older token (across a
            // sign-out/sign-in) must not end the new session.
            if let s = sentToken, s == token { onUnauthorized?() }
            throw APIError(message: human ?? "انتهت الجلسة، سجّل دخولك من جديد.",
                           code: machine, kind: .unauthorized)
        }
        if code >= 400 {
            // `message` للعرض، `error` رمز آلي للتفريع.
            throw APIError(message: human ?? machine ?? "خطأ \(code)",
                           code: machine, kind: .server)
        }
        return data
    }

    /// nil لو فاضي، حتى `{"message": ""}` ما ينتصر على رمز فيه معلومة.
    private static func nonEmpty(_ s: String?) -> String? {
        guard let t = s?.trimmingCharacters(in: .whitespacesAndNewlines),
              !t.isEmpty else { return nil }
        return t
    }

    // السطح غير المطبوع (JSON عام). داخلي حتى توصله الامتدادات.
    func request(_ path: String,
                 method: String = "GET",
                 body: [String: Any]? = nil,
                 auth: Bool = true) async throws -> [String: Any] {
        let bodyData = try body.map { try JSONSerialization.data(withJSONObject: $0) }
        let data = try await perform(path, method: method, bodyData: bodyData, auth: auth)
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
    }

    // السطح المطبوع للقراءة. الحقول الاختيارية nil بتنحذف من الـJSON = «بلا تغيير».
    func fetch<T: Decodable>(_ path: String,
                             method: String = "GET",
                             body: (any Encodable)? = nil,
                             auth: Bool = true,
                             timeout: TimeInterval = 30) async throws -> T {
        let bodyData = try body.map { try JSONEncoder().encode($0) }
        let data = try await perform(path, method: method, bodyData: bodyData,
                                     auth: auth, timeout: timeout)
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError(message: "تعذّر قراءة رد الخادم.", kind: .server)
        }
    }

    /// A body already encoded (the outbox keeps writes as bytes on disk).
    func sendData(_ path: String, method: String, body: Data?) async throws {
        _ = try await perform(path, method: method, bodyData: body, auth: true)
    }

    // السطح المطبوع للتعديل: يرسل جسماً Encodable ويتحقق من رمز الحالة فقط.
    func send(_ path: String,
              method: String,
              body: (any Encodable)? = nil,
              auth: Bool = true,
              bearer: String? = nil) async throws {
        let bodyData = try body.map { try JSONEncoder().encode($0) }
        _ = try await perform(path, method: method, bodyData: bodyData, auth: auth, bearer: bearer)
    }
}
