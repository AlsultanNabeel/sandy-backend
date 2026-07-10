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
            "serverUrl":    .text("عنوان الخادم"),
            "devLogin":     .text("أو دخول المطوّر (للتجربة)"),
            "ownerPassword": .text("كلمة سر المالك"),
            "login":        .text("دخول"),
            "appleFailed":  .text("فشل تسجيل الدخول بآبل"),
        ],
        en: [
            "loginBtn":     .text("Log In"),
            "subtitle":     .text("Personal Assistant"),
            "logout":       .text("Log out"),
            "title":        .text("Sandy"),
            "tagline":      .text("Your personal secretary"),
            "serverUrl":    .text("Server URL"),
            "devLogin":     .text("Or developer login (for testing)"),
            "ownerPassword": .text("Owner password"),
            "login":        .text("Log in"),
            "appleFailed":  .text("Sign in with Apple failed"),
        ]
    )
}
