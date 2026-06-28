import Foundation
import Security

// ─────────────────────────────────────────────────────────────────────────
//  Keychain — مخزن آمن بسيط لتوكن الدخول.
//
//  نحفظ التوكن بالـKeychain (مش UserDefaults) لأنه سرّ. الإتاحة
//  `AfterFirstUnlock` حتى تقدر النوايا/الويدجت تقرأه بالخلفية بعد أول فتح للجهاز.
//
//  لاحقًا لمشاركته مع تارجت الويدجت: نضيف `kSecAttrAccessGroup` (مجموعة تطبيقات).
// ─────────────────────────────────────────────────────────────────────────
enum Keychain {
    private static let service = "com.sandy.app"
    private static let account = "auth.token"

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
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
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
