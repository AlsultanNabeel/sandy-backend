import Foundation

// عنوان الخادم بمجموعة التطبيقات للويدجت وإضافة المشاركة (التوكن بالـKeychain المشترك).
// المفتاح لازم يطابق SandyShareExtension/ShareAPI.swift و SandyWidget/SandyTasksWidget.swift.
enum SharedAuth {
    static let appGroup = "group.com.sandy.app"
    static let baseURLKey = "share_base_url"
    /// نسخة التوكن القديمة (مكشوفة) من قبل ما ينتقل للـKeychain المشترك.
    private static let legacyTokenKey = "share_auth_token"

    static func mirror(baseURL: String) {
        guard let store = UserDefaults(suiteName: appGroup) else { return }
        store.set(baseURL, forKey: baseURLKey)
        // جهاز حدّث من نسخة كانت تكتب التوكن هون: نمسحه.
        store.removeObject(forKey: legacyTokenKey)
    }
}
