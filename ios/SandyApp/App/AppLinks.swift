import Foundation

/// The app's public links and support address, in one place.
///
/// ⚠️ Empty on purpose: fill them before the App Store release (Apple asks for a privacy
/// policy link). While a value is empty, Profile shows its row as «soon» and the mail
/// button stays hidden; nothing else needs to change when they are filled.
enum AppLinks {
    /// The privacy policy page, e.g. "https://sandy-ai.tech/privacy".
    static let privacyPolicy = ""
    /// The terms of use page, e.g. "https://sandy-ai.tech/terms".
    static let terms = ""
    /// Where «Email us» writes to, e.g. "support@sandy-ai.tech".
    static let supportEmail = ""

    static func url(_ link: String) -> URL? {
        link.isEmpty ? nil : URL(string: link)
    }
}

/// What a support note carries, so a problem can be traced to its build and phone.
enum AppInfo {
    static var version: String {
        let info = Bundle.main.infoDictionary
        let short = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build = info?["CFBundleVersion"] as? String ?? "?"
        return "\(short) (\(build))"
    }

    /// The model identifier, e.g. "iPhone14,2".
    static var device: String {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { raw in
            String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
        }
    }

    static var system: String {
        "iOS " + ProcessInfo.processInfo.operatingSystemVersionString
    }
}
