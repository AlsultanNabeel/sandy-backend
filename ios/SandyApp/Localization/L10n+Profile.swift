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
            "display": .text("العرض"),
            "display.appearance": .text("المظهر"),
            "display.system": .text("تلقائي"),
            "display.light": .text("فاتح"),
            "display.dark": .text("غامق"),
            "display.text": .text("حجم الخط"),
            "display.elements": .text("حجم العناصر"),
            "display.deviceSize": .text("حسب الجهاز"),
            "display.reset": .text("رجّع الأحجام زي الجهاز"),
            "display.previewTitle": .text("هيك رح يبين التطبيق"),
            "display.previewBody": .text("حرّك الشرائط وشوف الفرق فوراً."),
            "display.preview": .text("معاينة العرض"),
            "signOut":           .text("تسجيل الخروج"),
            "signOutAsk":        .text("أكيد بدك تطلع من حسابك؟"),
            "signOutNote":       .text("التغييرات اللي لسا ما وصلت السيرفر رح تضيع."),
            "signOutCancel":     .text("خليني"),
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
            "display": .text("Display"),
            "display.appearance": .text("Appearance"),
            "display.system": .text("Automatic"),
            "display.light": .text("Light"),
            "display.dark": .text("Dark"),
            "display.text": .text("Text size"),
            "display.elements": .text("Element size"),
            "display.deviceSize": .text("Device size"),
            "display.reset": .text("Reset to device sizes"),
            "display.previewTitle": .text("This is how the app will look"),
            "display.previewBody": .text("Move the sliders and see it change."),
            "display.preview": .text("Display preview"),
            "signOut":           .text("Sign out"),
            "signOutAsk":        .text("Sign out of your account?"),
            "signOutNote":       .text("Changes that haven't reached the server yet will be lost."),
            "signOutCancel":     .text("Stay"),
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
