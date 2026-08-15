import SwiftUI
#if canImport(GoogleSignIn)
import GoogleSignIn
#endif

// ─────────────────────────────────────────────────────────────────────────
//  GoogleAuth — تسجيل الدخول بجوجل عبر حزمة GoogleSignIn.
//
//  يفتح تدفّق جوجل، يرجّع الـid token، واللي بعدها نبعته للباك‑إند
//  (`/api/auth/google`) اللي بيتحقّق منه ويصكّ توكن ساندي.
//
//  متطلّبات إكس‌كود (مرّة وحدة):
//   • إضافة حزمة GoogleSignIn-iOS عبر Swift Package Manager.
//   • إضافة URL Scheme = معكوس المعرّف (REVERSED_CLIENT_ID) من ملف جوجل plist.
//   • نداء `GIDSignIn.sharedInstance.handle(url)` بـ onOpenURL (معمول بـ SandyApp).
//
//  المعرّف عام (مش سري) فنخليه ثابت هون.
//
//  الحزمة محاطة بـ `#if canImport` — نفس نمط `SubscriptionManager` مع RevenueCat،
//  ولنفس السببين. الأول: التطبيق بينبني قبل ما حدا يضيف الحزمة بإكس‌كود، فمين
//  بيستنسخ المشروع بيوصل لشاشة تشتغل بدل خطأ ترجمة. والتاني: بوابة الترجمة
//  بالتكامل المستمر بتشغّل المترجم ع الملفات مباشرة بلا ملف مشروع، فما عندها
//  طريقة تحل الحزم — ومن غير هاد، أول مرّة اشتغلت فيها وقعت ع سطر `import`
//  مش ع غلط بالكود.
//
//  الدالة موجودة بالحالتين ونفس التوقيع، فـ`AuthView` ما بتعرف الفرق: بتنجح
//  لما الحزمة موجودة، وبترمي خطأ مفهوم لما تكون ناقصة.
// ─────────────────────────────────────────────────────────────────────────
enum GoogleAuth {
    /// معرّف عميل جوجل لـ iOS.
    static let clientID =
        "674790516773-ahf3kvtl8emvdid9b7brjfq7d63t8cqe.apps.googleusercontent.com"

    /// يفتح نافذة جوجل ويرجّع الـid token (أو يرمي خطأ).
    @MainActor
    static func signIn() async throws -> String {
        #if !canImport(GoogleSignIn)
        // الحزمة مش مضافة بإكس‌كود. الرسالة بتقول شو ناقص بالضبط بدل ما الزر
        // يضغط وما يصير إشي.
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

    /// الـView controller الجذري — لازم لتقديم نافذة جوجل.
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
