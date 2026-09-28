import Foundation

// ─────────────────────────────────────────────────────────────────────────
//  SharedAuth — عنوان الخادم بمجموعة التطبيقات المشتركة، عشان الويدجت وإضافة
//  المشاركة يعرفوا وين يبعتوا.
//
//  التوكن نفسه مش هون: بيقروه من الـKeychain بمجموعة الوصول المشتركة (شوف
//  Core/Auth/Keychain.swift). العنوان مش سرّ، فمكانه الطبيعي UserDefaults.
//
//  الكتابة بتصير من `APIClient` لما يتغيّر العنوان، ومرّة بالإقلاع.
//
//  لازم المفتاح يضل مطابق لـ SandyShareExtension/ShareAPI.swift
//  و SandyWidget/SandyTasksWidget.swift.
// ─────────────────────────────────────────────────────────────────────────
enum SharedAuth {
    static let appGroup = "group.com.sandy.app"
    static let baseURLKey = "share_base_url"
    /// نسخة التوكن القديمة (مكشوفة) من قبل ما ينتقل للـKeychain المشترك.
    private static let legacyTokenKey = "share_auth_token"

    static func mirror(baseURL: String) {
        guard let store = UserDefaults(suiteName: appGroup) else { return }
        store.set(baseURL, forKey: baseURLKey)
        // جهاز حدّث من نسخة كانت تكتب التوكن هون: نمسحه، ما بينقرا من هون بعد اليوم.
        store.removeObject(forKey: legacyTokenKey)
    }
}
