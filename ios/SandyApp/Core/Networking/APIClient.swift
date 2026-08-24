import Foundation

/// Talks to the Sandy backend (the Python API we built).
///
/// Conforms to `APIClientProtocol` (the transport seam); each feature's
/// endpoint methods live in the `APIClient+<Feature>` extensions under
/// `Core/Networking/`.
final class APIClient: APIClientProtocol {
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
            (data, resp) = try await URLSession.shared.data(for: req)
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
