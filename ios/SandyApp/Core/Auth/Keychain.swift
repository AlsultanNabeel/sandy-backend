import Foundation
import Security

// ─────────────────────────────────────────────────────────────────────────
//  Keychain — مخزن آمن بسيط لتوكن الدخول.
//
//  نحفظ التوكن بالـKeychain (مش UserDefaults) لأنه سرّ. الإتاحة
//  `AfterFirstUnlockThisDeviceOnly`: النوايا/الويدجت تقرأه بالخلفية بعد أول فتح،
//  و`ThisDeviceOnly` تمنعه من الرجوع لجهاز ثاني عبر نسخة احتياطية مشفّرة.
//
//  **مجموعة الوصول = مجموعة التطبيقات.** العنصر بينحفظ بـ`group.com.sandy.app`،
//  فالويدجت وإضافة المشاركة بيقروه من هون مباشرة. قبل كانت في نسخة منه بـ
//  UserDefaults المشتركة، وهاد ملف plist عادي مش مشفّر، فالسرّ كان مكشوف لأي
//  تارجت بالمجموعة وبالنسخ الاحتياطية. مجموعة التطبيقات بتنفع كمجموعة وصول
//  للـKeychain بدون استحقاق `keychain-access-groups`، فما تغيّر شي بالاستحقاقات.
//
//  القراءة والمسح بدون مجموعة: بيلاقوا العنصر وين ما كان، فالتوكن اللي انحفظ
//  قبل هالتغيير بينقرا، و`APIClient` بيعيد حفظه بالمجموعة بأول إقلاع.
//
//  لازم الخدمة والحساب يضلّوا مطابقين لـ SandyWidget/SandyTasksWidget.swift
//  و SandyShareExtension/ShareAPI.swift.
// ─────────────────────────────────────────────────────────────────────────
enum Keychain {
    private static let service = "com.sandy.app"
    private static let account = "auth.token"
    private static let accessGroup = "group.com.sandy.app"

    /// يحفظ التوكن (أو يمسحه لو nil).
    static func saveToken(_ value: String?) {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        // نمسح القديم دايمًا (أبسط من التحديث، ويغطّي حالة المسح).
        SecItemDelete(base as CFDictionary)
        guard let value, let data = value.data(using: .utf8) else { return }
        var add = base
        add[kSecValueData as String] = data
        add[kSecAttrAccessGroup as String] = accessGroup
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }

    /// يقرأ التوكن المحفوظ (أو nil).
    static func loadToken() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data,
              let value = String(data: data, encoding: .utf8) else { return nil }
        return value
    }
}
