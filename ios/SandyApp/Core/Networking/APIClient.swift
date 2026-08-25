import Foundation

/// Talks to the Sandy backend (the Python API we built).
///
/// Conforms to `APIClientProtocol` (the transport seam); each feature's
/// endpoint methods live in the `APIClient+<Feature>` extensions under
/// `Core/Networking/`.
final class APIClient: APIClientProtocol {
    /// The app's own session, so transport policy lives in one place.
    ///
    /// **`waitsForConnectivity` is deliberately OFF**, and that is worth saying
    /// because it is the obvious thing to reach for and it makes this app
    /// worse. With it on, the session ignores the per-request timeout during a
    /// connectivity wait — the only bound left is `timeoutIntervalForResource`,
    /// which caps the *entire transfer*, not idle time. That forces a choice
    /// between two broken settings: leave the resource timeout at its seven-day
    /// default and an offline phone shows a spinner forever, or lower it and
    /// the chat SSE stream and every photo upload get cut off mid-flight by the
    /// same number. A caller asking for `timeout: 8` would get neither.
    ///
    /// What that setting was wanted for is the Wi-Fi to cellular handover, and
    /// `sendWithRetry` below covers it properly: the connection drops, the
    /// backoff gives the handover its beat to settle, the retry succeeds — and
    /// a phone that is genuinely offline still fails in a second, which is what
    /// someone staring at a spinner needs.
    ///
    /// No blanket `Accept` header either: three call sites fetch a JPEG, a WAV
    /// and an SSE stream, so `application/json` would be a lie on each. Cache
    /// policy stays the default — these are per-user reads behind a bearer
    /// token, and a stale list off disk is worse than a slow one.
    ///
    /// Not private: the per-feature extensions build their own requests and
    /// must send them the same way. A policy applied to this file and not to
    /// those is not a policy.
    static let session: URLSession = URLSession(configuration: .default)

    /// How many times a *safe* request is retried before the error is shown.
    ///
    /// There was no retry anywhere, so one dropped packet on cellular was a
    /// visible failure with a red banner. Only idempotent methods qualify:
    /// retrying a POST could create the same task twice, which is worse than
    /// the error it avoids.
    static let idempotentMethods: Set<String> = ["GET", "HEAD"]
    static let maxRetries = 2

    var baseURL: String
    /// توكن الدخول — يُحفظ تلقائياً بالـKeychain عند أي تغيير (وnil = تسجيل خروج).
    /// فالجلسة تستعيد نفسها عند الإقلاع، والنوايا/الويدجت تقدر تصادق بمعزل.
    var token: String? {
        didSet { Keychain.saveToken(token) }
    }

    /// Called when an authenticated request gets a 401, so the app can route to login.
    var onUnauthorized: (() -> Void)?

    /// هوية المستخدم مفكوكة من حمولة الـJWT (بدون تحقّق — للعرض/الربط فقط، مثل
    /// تمريرها لـRevenueCat كـ app_user_id حتى يطابق حسابه بالباك-إند). nil لو ما
    /// في توكن أو تعذّر الفك.
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

    init(baseURL: String) {
        self.baseURL = baseURL
        // نحمّل التوكن المحفوظ (لو في) — التعيين بالـinit ما يشغّل didSet فما يعيد الحفظ.
        self.token = Keychain.loadToken()
    }

    /// Send, retrying a transient network failure on a safe method.
    ///
    /// Cancellation is never retried — it is a decision, not a failure. Nor is
    /// anything the server said: a 500 that repeats is the server's problem and
    /// hammering it is not the client's job. This is only for the case the
    /// phone creates by being a phone — a connection that dropped between the
    /// request leaving and the response arriving.
    static func sendWithRetry(_ req: URLRequest,
                              method: String) async throws -> (Data, URLResponse) {
        var attempt = 0
        while true {
            do {
                return try await session.data(for: req)
            } catch let error as URLError {
                let retryable: Set<URLError.Code> = [
                    .networkConnectionLost, .timedOut, .cannotConnectToHost,
                    .dnsLookupFailed, .notConnectedToInternet,
                ]
                guard idempotentMethods.contains(method),
                      retryable.contains(error.code),
                      attempt < maxRetries
                else { throw error }
                attempt += 1
                // Back off so a retry does not land in the same dead moment the
                // first one did — a handover takes a beat to settle.
                //
                // `try`, not `try?`: the sleep is this loop's only cancellation
                // checkpoint, and swallowing it would send another request for
                // a screen the user has already left.
                try await Task.sleep(nanoseconds: UInt64(attempt) * 400_000_000)
            }
        }
    }

    // النقل الأساسي: يبني الطلب، يرسله، يترجم رمز الحالة لأخطاء APIError، ويرجّع الجسم
    // الخام. تبني عليه الأسطح الثلاثة تحت (غير المطبوع + المطبوعان) فمنطق الشبكة
    // والأخطاء مكتوب مرة واحدة.
    /// نداء بيرجّع البايتات زي ما هي — للردود اللي مش JSON، زي صورة.
    ///
    /// موجودة هون مش بملف الأجهزة عشان تشارك `perform`: العنوان الأساسي
    /// والتوكن ومعالجة انتهاء الجلسة كلها بمكان واحد. أي نداء بيبني طلبه
    /// بإيده بيصير لازم يتذكّر التلاتة، وبينسى وحدة منهن.
    func rawPost(_ path: String, timeout: TimeInterval = 30) async throws -> Data {
        let data = try await perform(path, method: "POST",
                                     bodyData: Data("{}".utf8),
                                     auth: true, timeout: timeout)
        guard !data.isEmpty else { throw APIError(message: "رد فاضي") }
        return data
    }

    /// GET بترجّع البايتات زي ما هي — للردود اللي مش JSON، زي الصور.
    func rawGet(_ path: String, timeout: TimeInterval = 15) async throws -> Data {
        try await perform(path, method: "GET", bodyData: nil,
                          auth: true, timeout: timeout)
    }

    private func perform(_ path: String,
                         method: String,
                         bodyData: Data?,
                         auth: Bool,
                         timeout: TimeInterval = 30) async throws -> Data {
        guard let url = URL(string: baseURL + path) else { throw APIError(message: "عنوان غير صالح") }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = timeout
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if auth, let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        req.httpBody = bodyData

        let data: Data
        let resp: URLResponse
        do {
            (data, resp) = try await Self.sendWithRetry(req, method: method)
        } catch let urlError as URLError {
            // A cancelled request (e.g. a refresh superseded by a newer tap)
            // must keep its cancellation identity so callers' isCancellation
            // checks can suppress it — don't collapse it into a generic
            // connection error (that showed a spurious "couldn't load" notice).
            if urlError.code == .cancelled { throw urlError }
            // Offline, timed out, or connection dropped — all surface as one
            // clear "check your internet" error the UI can act on.
            throw APIError(message: "تعذّر الاتصال بالخادم. تأكد من الإنترنت وحاول مرة ثانية.", kind: .connection)
        }
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        let machine = Self.nonEmpty(body?["error"] as? String)
        let human = Self.nonEmpty(body?["message"] as? String)

        // 401 على طلب **موثَّق** = الجلسة ماتت. 401 على طلب مش موثَّق = محاولة
        // دخول فشلت، وهاي شغلة تانية تمامًا.
        //
        // الشرط كان بس ع النداء `onUnauthorized?()`، والرسالة كانت وحدة
        // للحالتين. فمين بيغلط بكلمة السر كان الخادم يرجّعله
        // `invalid_credentials` وياخد «انتهت الجلسة، سجّل دخولك من جديد» —
        // وهو عم يسجّل دخول. وشاشة الدخول عندها ترجمة عربية جاهزة لهالرمز
        // (`friendlyAuthError`) ما كانت توصلها ولا مرّة.
        if code == 401 && auth {
            onUnauthorized?()
            throw APIError(message: human ?? "انتهت الجلسة، سجّل دخولك من جديد.",
                           code: machine, kind: .unauthorized)
        }
        if code >= 400 {
            // `message` للعرض، `error` للتفريع — حقلان، مش حقل بمعنيين.
            //
            // الخادم بيبعت التنين وهنّي مش نفس الإشي: `error` رمز آلي بتفرّع
            // عليه الشاشات (`rate_limited`، `already_claimed`)، و`message`
            // الجملة المكتوبة عشان الإنسان يقراها. قراءة `error` لحاله كانت
            // بتعرض «daily_quota_exceeded» لمستخدم عربي وبتسمّيها شرحًا.
            throw APIError(message: human ?? machine ?? "خطأ \(code)",
                           code: machine, kind: .server)
        }
        return data
    }

    /// النص بعد قصّ الفراغات، أو nil لو طلع فاضي — عشان `{"message": ""}` ما
    /// ينتصر على رمز فيه معلومة.
    private static func nonEmpty(_ s: String?) -> String? {
        guard let t = s?.trimmingCharacters(in: .whitespacesAndNewlines),
              !t.isEmpty else { return nil }
        return t
    }

    // السطح غير المطبوع (JSON عام). داخلي (مش private) حتى توصله امتدادات APIClient
    // الموزّعة على ملفات تانية اللي لسّا ما اتهاجرت لنماذج Codable المطبوعة.
    func request(_ path: String,
                 method: String = "GET",
                 body: [String: Any]? = nil,
                 auth: Bool = true) async throws -> [String: Any] {
        let bodyData = try body.map { try JSONSerialization.data(withJSONObject: $0) }
        let data = try await perform(path, method: method, bodyData: bodyData, auth: auth)
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
    }

    // السطح المطبوع للقراءة: يفكّ رد الخادم إلى نموذج Codable. جسم الطلب Encodable
    // اختياري — الحقول الاختيارية nil تُحذف تلقائياً من الـJSON (encodeIfPresent) فتبقى
    // دلالة "الحقل الغائب = بلا تغيير" اللي كانت تُبنى يدويًا بقواميس [String: Any].
    func fetch<T: Decodable>(_ path: String,
                             method: String = "GET",
                             body: (any Encodable)? = nil,
                             auth: Bool = true) async throws -> T {
        let bodyData = try body.map { try JSONEncoder().encode($0) }
        let data = try await perform(path, method: method, bodyData: bodyData, auth: auth)
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError(message: "تعذّر قراءة رد الخادم.", kind: .server)
        }
    }

    // السطح المطبوع للتعديل (POST/PATCH/DELETE) بلا رد يُقرأ: يرسل جسماً Encodable
    // ويتحقق من رمز الحالة فقط.
    func send(_ path: String,
              method: String,
              body: (any Encodable)? = nil,
              auth: Bool = true) async throws {
        let bodyData = try body.map { try JSONEncoder().encode($0) }
        _ = try await perform(path, method: method, bodyData: bodyData, auth: auth)
    }
}
