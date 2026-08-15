import Foundation

// Namespace: profile — the account screen (drops in LanguageToggle). Holds the
// warm identity copy (avatar + preferred name + interests + edit sheet). FILLED.
//
// Usage:  Text(lang.s("profile.title"))
enum L10nProfile {
    static let ns = "profile"

    static let table = L10nTable(
        ar: [
            "title":             .text("حسابي"),
            "language":          .text("اللغة"),
            "signOut":           .text("تسجيل الخروج"),
            "subtitle":          .text("هاي ملفّك مع ساندي — خليه يحكي عنك 🌿"),
            "nameFallback":      .text("صديق ساندي"),
            "preferredName":     .text("اسمك المفضّل"),
            "interests":         .text("اهتماماتك"),
            "preferredNameEdit": .text("الاسم المفضّل"),
            "interestsEmpty":    .text("لم تُضِف اهتماماتك بعد — أضف ما تحبّه."),
            "edit":              .text("تعديل الملف"),
            "namePlaceholder":   .text("كيف بتحب ساندي تناديك؟"),
            "addInterest":       .text("أضف اهتمام…"),
            "interestsHint":     .text("أضِف اهتمام واحد على الأقل ليعرفك ساندي أكتر."),
            "saveFailed":        .text("تعذّر حفظ التعديلات. أعد المحاولة بعد قليل."),
            "archive":           .text("أدوات وأرشيف"),
        ],
        en: [
            "title":             .text("Account"),
            "language":          .text("Language"),
            "signOut":           .text("Sign out"),
            "subtitle":          .text("This is your profile with Sandy — let it speak about you 🌿"),
            "nameFallback":      .text("Sandy's friend"),
            "preferredName":     .text("Your preferred name"),
            "interests":         .text("Your interests"),
            "preferredNameEdit": .text("Preferred name"),
            "interestsEmpty":    .text("No interests added yet — add something you like."),
            "edit":              .text("Edit profile"),
            "namePlaceholder":   .text("What would you like Sandy to call you?"),
            "addInterest":       .text("Add an interest…"),
            "interestsHint":     .text("Add at least one interest so Sandy can get to know you better."),
            "saveFailed":        .text("Couldn't save your changes. Try again shortly."),
            "archive":           .text("Tools & Archive"),
        ]
    )
}
