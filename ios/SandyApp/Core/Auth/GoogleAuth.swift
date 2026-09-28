import SwiftUI
#if canImport(GoogleSignIn)
import GoogleSignIn
#endif

// تسجيل الدخول بجوجل؛ الـid token بينبعت لـ `/api/auth/google`.
// `#if canImport` حتى يتبنى التطبيق وبوابة CI (بلا ملف مشروع) بدون الحزمة.
enum GoogleAuth {
    static let clientID =
        "674790516773-ahf3kvtl8emvdid9b7brjfq7d63t8cqe.apps.googleusercontent.com"

    @MainActor
    static func signIn() async throws -> String {
        #if !canImport(GoogleSignIn)
        // الحزمة مش مضافة: رسالة واضحة بدل زر ما بيعمل إشي.
        throw APIError(message: "حزمة GoogleSignIn مش مضافة بالمشروع")
        #else
        GIDSignIn.sharedInstance.configuration = GIDConfiguration(clientID: clientID)
        guard let root = rootViewController() else {
            throw APIError(message: "ما قدرنا نفتح نافذة جوجل")
        }
        return try await withCheckedThrowingContinuation { cont in
            GIDSignIn.sharedInstance.signIn(withPresenting: root) { result, error in
                if let error {
                    cont.resume(throwing: error)
                    return
                }
                guard let idToken = result?.user.idToken?.tokenString else {
                    cont.resume(throwing: APIError(message: "ما رجع توكن من جوجل"))
                    return
                }
                cont.resume(returning: idToken)
            }
        }
        #endif
    }

    @MainActor
    private static func rootViewController() -> UIViewController? {
        let scene = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive } ??
            (UIApplication.shared.connectedScenes.first as? UIWindowScene)
        return scene?.keyWindow?.rootViewController
            ?? scene?.windows.first?.rootViewController
    }
}
