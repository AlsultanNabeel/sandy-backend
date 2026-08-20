import Foundation

// Namespace: auth — sign-in / dev-login screen strings. Mirrors the web
// dict/login.js (kept flat). FILLED by the AuthView migration.
//
// Usage:  Text(lang.s("auth.login"))
enum L10nAuth {
    static let ns = "auth"

    static let table = L10nTable(
        ar: [
            "loginBtn":     .text("تسجيل الدخول"),
            "subtitle":     .text("المساعد الشخصي"),
            "logout":       .text("خروج"),
            "title":        .text("ساندي"),
            "tagline":      .text("سكرتيرك الشخصي"),
            // `serverUrl` و`devLogin` و`ownerPassword` انحذفوا: أدوات تطوير
            // كانت مكشوفة بأول شاشة يشوفها الزبون. وحقل العنوان أخطرهن —
            // بيوجّه التطبيق كله، وبياناته معه، ع خادم مش إلنا.
            "login":        .text("دخول"),
            "appleFailed":  .text("فشل تسجيل الدخول بآبل"),
        ],
        en: [
            "loginBtn":     .text("Log In"),
            "subtitle":     .text("Personal Assistant"),
            "logout":       .text("Log out"),
            "title":        .text("Sandy"),
            "tagline":      .text("Your personal secretary"),
            "login":        .text("Log in"),
            "appleFailed":  .text("Sign in with Apple failed"),
        ]
    )
}
