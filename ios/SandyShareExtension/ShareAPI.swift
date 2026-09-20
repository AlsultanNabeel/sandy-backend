import Foundation

// ─────────────────────────────────────────────────────────────────────────
//  ShareAPI — عميل صغير للباك‑إند خاص بإضافة المشاركة.
//
//  الإضافة ما بتشوف كود التطبيق، فهاد نسخة مصغّرة: التوكن والعنوان بيجوا من
//  مجموعة التطبيقات (التطبيق بيكتبهم بـ Core/Shared/SharedAuth.swift).
//  المفاتيح لازم تضل مطابقة لهداك الملف.
// ─────────────────────────────────────────────────────────────────────────

enum ShareText {
    static let appGroup = "group.com.sandy.app"

    /// لغة التطبيق (بيكتبها التطبيق للويدجت)، وإلا لغة الجهاز.
    static var isArabic: Bool {
        if let lang = UserDefaults(suiteName: appGroup)?.string(forKey: "app_lang") {
            return lang != "en"
        }
        return Locale.current.language.languageCode?.identifier == "ar"
    }

    static func t(_ ar: String, _ en: String) -> String { isArabic ? ar : en }
}

enum ShareError: LocalizedError {
    case signedOut
    case limit
    case connection
    case server(String?)

    var errorDescription: String? {
        switch self {
        case .signedOut:
            return ShareText.t("افتح ساندي وسجّل دخول أول، وبعدين جرّب كمان مرة.",
                               "Open Sandy and sign in first, then try again.")
        case .limit:
            return ShareText.t("خلصت رسائل اليوم. جرّب بكرا.",
                               "You've reached today's limit. Try again tomorrow.")
        case .connection:
            return ShareText.t("تعذّر الاتصال. تأكد من الإنترنت وجرّب كمان مرة.",
                               "Couldn't connect. Check your internet and try again.")
        case .server(let message):
            return message ?? ShareText.t("صار خطأ، جرّب كمان مرة.", "Something went wrong, try again.")
        }
    }
}

struct ShareAPI {
    static let tokenKey = "share_auth_token"
    static let baseURLKey = "share_base_url"
    /// نفس الافتراضي بـ SandyApp/Core/Networking/Backend.swift.
    static let defaultURL = "https://sandy-robot-3da0693d32f7.herokuapp.com"

    let baseURL: String
    let token: String

    /// nil = المستخدم مش مسجّل دخول بالتطبيق (أو ما فتحه من وقت ما انضافت الإضافة).
    static func load() -> ShareAPI? {
        let store = UserDefaults(suiteName: ShareText.appGroup)
        guard let token = store?.string(forKey: tokenKey), !token.isEmpty else { return nil }
        let saved = store?.string(forKey: baseURLKey) ?? ""
        return ShareAPI(baseURL: saved.isEmpty ? defaultURL : saved, token: token)
    }

    /// POST بجسم JSON، بيرجّع الرد كقاموس. رموز الحالة بتتحوّل لـ ShareError.
    func post(_ path: String, _ body: [String: Any], timeout: TimeInterval = 60) async throws -> [String: Any] {
        guard let url = URL(string: baseURL + path) else { throw ShareError.server(nil) }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = timeout
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)

        let data: Data
        let resp: URLResponse
        do {
            (data, resp) = try await URLSession.shared.data(for: req)
        } catch {
            throw ShareError.connection
        }
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        switch code {
        case 200..<300: return json
        case 401: throw ShareError.signedOut
        case 429: throw ShareError.limit
        default: throw ShareError.server(json["message"] as? String)
        }
    }
}
