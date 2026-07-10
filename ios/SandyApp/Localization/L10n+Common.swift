import Foundation

// Namespace: common — shared button labels & generic UI strings used everywhere.
// Mirrors the web dict/common.js (kept flat). FILLED.
//
// Usage:  Text(lang.s("common.add"))
enum L10nCommon {
    static let ns = "common"

    static let table = L10nTable(
        ar: [
            "add":     .text("إضافة"),
            "cancel":  .text("إلغاء"),
            "save":    .text("حفظ"),
            "delete":  .text("حذف"),
            "edit":    .text("تعديل"),
            "done":    .text("تم"),
            "loading": .text("...جاري التحميل"),
            "error":   .text("معلش، صار خطأ بسيط — جرّب كمان مرة."),
            "retry":   .text("إعادة المحاولة"),
            "empty":   .text("ما في شيء هنا بعد"),
            "language": .text("اللغة"),
        ],
        en: [
            "add":     .text("Add"),
            "cancel":  .text("Cancel"),
            "save":    .text("Save"),
            "delete":  .text("Delete"),
            "edit":    .text("Edit"),
            "done":    .text("Done"),
            "loading": .text("Loading…"),
            "error":   .text("Oops, something went wrong — try again."),
            "retry":   .text("Retry"),
            "empty":   .text("Nothing here yet"),
            "language": .text("Language"),
        ]
    )
}
