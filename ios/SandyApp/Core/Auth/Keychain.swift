import Foundation
import Security

// `AfterFirstUnlockThisDeviceOnly`: الويدجت/النوايا تقرأه بالخلفية، وما بيرجع لجهاز تاني من نسخة احتياطية.
// محفوظ بمجموعة `group.com.sandy.app` حتى تقراه الإضافات؛ الخدمة والحساب لازم يطابقوا SandyTasksWidget و ShareAPI.
enum Keychain {
    private static let service = "com.sandy.app"
    private static let account = "auth.token"
    private static let accessGroup = "group.com.sandy.app"

    /// The signed-in server's token is always the shared one the extensions read; the other
    /// server's waits in a slot of its own until the app switches back.
    static func parkedAccount(_ server: Backend.Server) -> String { "\(account).\(server.rawValue)" }

    static func saveToken(_ value: String?, account: String = account) {
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

    static func loadToken(account: String = account) -> String? {
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

/// Where `APIClient` keeps the session token, and the other server's while it is not the
/// one in use (`APIClient.switchServer`). The app's is the shared Keychain; tests keep
/// theirs in memory.
protocol TokenStore {
    func load() -> String?
    func save(_ token: String?)
    func loadParked(_ server: Backend.Server) -> String?
    func saveParked(_ token: String?, _ server: Backend.Server)
}

struct KeychainTokenStore: TokenStore {
    func load() -> String? { Keychain.loadToken() }
    func save(_ token: String?) { Keychain.saveToken(token) }
    func loadParked(_ server: Backend.Server) -> String? {
        Keychain.loadToken(account: Keychain.parkedAccount(server))
    }
    func saveParked(_ token: String?, _ server: Backend.Server) {
        Keychain.saveToken(token, account: Keychain.parkedAccount(server))
    }
}
