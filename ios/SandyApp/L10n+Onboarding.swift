import Foundation

// Namespace: onboarding — first-run getting-to-know-you screen. STARTER stub —
// the OnboardingView migration agent fills the rest into this table (ar + en).
//
// Usage:  Text(lang.s("onboarding.title"))
enum L10nOnboarding {
    static let ns = "onboarding"

    static let table = L10nTable(
        ar: [
            "title":             .text("نتعرّف عليك 👋"),
            "nameLabel":         .text("شو تحب ساندي تناديك؟"),
            "namePlaceholder":   .text("اسمك المفضّل"),
            "interestsLabel":    .text("اهتماماتك (افصلها بفاصلة)"),
            "interestsPlaceholder": .text("مثلاً: قراءة، رياضة، سفر"),
            "save":              .text("يلا نبدأ"),
        ],
        en: [
            "title":             .text("Getting to know you 👋"),
            "nameLabel":         .text("What would you like Sandy to call you?"),
            "namePlaceholder":   .text("Your preferred name"),
            "interestsLabel":    .text("Your interests (separate with commas)"),
            "interestsPlaceholder": .text("e.g. reading, sports, travel"),
            "save":              .text("Let's start"),
        ]
    )
}
