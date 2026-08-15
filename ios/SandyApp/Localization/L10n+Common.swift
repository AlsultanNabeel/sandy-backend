import Foundation

// Namespace: common — shared button labels & generic UI strings used everywhere.
// Mirrors the web dict/common.js (kept flat). FILLED.
//
// Usage:  Text(lang.s("common.add"))
enum L10nCommon {
    static let ns = "common"

    static let table = L10nTable(
        ar: [
            "demoData": .text("بيانات تجريبية"),
            "add":     .text("إضافة"),
            "cancel":  .text("إلغاء"),
            "save":    .text("حفظ"),
            "delete":  .text("حذف"),
            "edit":    .text("تعديل"),
            "done":    .text("تم"),
            "loading": .text("...جاري التحميل"),
            "error":   .text("حدث خطأ. أعد المحاولة."),
            "retry":   .text("إعادة المحاولة"),
            "empty":   .text("لا يوجد شيء هنا بعد"),
            "language": .text("اللغة"),
        ],
        en: [
            "demoData": .text("Demo data"),
            "add":     .text("Add"),
            "cancel":  .text("Cancel"),
            "save":    .text("Save"),
            "delete":  .text("Delete"),
            "edit":    .text("Edit"),
            "done":    .text("Done"),
            "loading": .text("Loading…"),
            "error":   .text("Something went wrong. Try again."),
            "retry":   .text("Retry"),
            "empty":   .text("Nothing here yet"),
            "language": .text("Language"),
        ]
    )
}
