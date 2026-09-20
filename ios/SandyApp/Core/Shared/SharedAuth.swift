import Foundation

// ─────────────────────────────────────────────────────────────────────────
//  SharedAuth — نسخة من توكن الدخول وعنوان الخادم بمجموعة التطبيقات المشتركة،
//  عشان إضافة المشاركة (SandyShare) تقدر تكلّم الباك‑إند.
//
//  ليش مش الـKeychain؟ مشاركة عنصر الـKeychain بين التطبيق والإضافة بدها
//  مجموعة وصول (keychain-access-groups) بالاستحقاقات للتارجتين. مجموعة
//  التطبيقات موجودة أصلاً (group.com.sandy.app)، فالنسخة هون أبسط وما بتغيّر
//  استحقاقات التطبيق. الـKeychain بيضل هو المصدر الأساسي للتطبيق.
//
//  الكتابة بتصير من `APIClient` لما يتغيّر التوكن (دخول/خروج) أو العنوان، ومرّة
//  بالإقلاع لحساب مسجّل من قبل. تسجيل الخروج (توكن nil) بيمسح النسخة.
//
//  لازم المفاتيح تضل مطابقة لـ ios/SandyShare/ShareAPI.swift.
// ─────────────────────────────────────────────────────────────────────────
enum SharedAuth {
    static let appGroup = "group.com.sandy.app"
    static let tokenKey = "share_auth_token"
    static let baseURLKey = "share_base_url"

    /// يكتب التوكن + العنوان للإضافة، أو يمسح التوكن لو nil/فاضي.
    static func mirror(token: String?, baseURL: String) {
        guard let store = UserDefaults(suiteName: appGroup) else { return }
        if let token, !token.isEmpty {
            store.set(token, forKey: tokenKey)
            store.set(baseURL, forKey: baseURLKey)
        } else {
            store.removeObject(forKey: tokenKey)
        }
    }
}
