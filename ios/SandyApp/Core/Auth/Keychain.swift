import Foundation
import Security

// `AfterFirstUnlockThisDeviceOnly`: الويدجت/النوايا تقرأه بالخلفية، وما بيرجع لجهاز تاني من نسخة احتياطية.
// محفوظ بمجموعة `group.com.sandy.app` حتى تقراه الإضافات؛ الخدمة والحساب لازم يطابقوا SandyTasksWidget و ShareAPI.
enum Keychain {
    private static let service = "com.sandy.app"
    private static let account = "auth.token"
    private static let accessGroup = "group.com.sandy.app"

    static func saveToken(_ value: String?) {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(base as CFDictionary)
        guard let value, let data = value.data(using: .utf8) else { return }
        var add = base
        add[kSecValueData as String] = data
        add[kSecAttrAccessGroup as String] = accessGroup
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }

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
