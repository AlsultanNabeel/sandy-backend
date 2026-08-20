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
            // `devLogin` و`ownerPassword` انحذفوا مع دخول المطوّر — حساب واحد
            // بكلمة سرّ مشتركة، كل من بيعرفها بيصير نفس الشخص.
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
            "login":        .text("Log in"),
            "appleFailed":  .text("Sign in with Apple failed"),
        ]
    )
}
