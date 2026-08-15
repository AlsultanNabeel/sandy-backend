import Foundation

// Namespace: memory — the Memory tab (what Sandy remembers about you). Real facts
// from /api/memory; excludes Sandy's internal/system memory.
enum L10nMemory {
    static let ns = "memory"

    static let table = L10nTable(
        ar: [
            "intro":       .text("هاي المعلومات اللي ساندي متذكّراها عنك — تقدر تضيف أو تعدّل أو تحذف أي وحدة."),
            "empty":       .text("لم تُحفظ أي معلومات عنك بعد — كلما تحدّثتما أكثر، عرفتك أكثر."),
            "errorLoad":   .text("تعذّر تحميل الذاكرة. اسحب للتحديث."),
            "errorDelete": .text("تعذّر الحذف. أعد المحاولة."),
            "errorAdd":    .text("تعذّر حفظ المعلومة. أعد المحاولة."),
            "errorEdit":   .text("تعذّر تعديل المعلومة. أعد المحاولة."),

            // إجراءات الصف
            "add":         .text("إضافة معلومة"),
            "edit":        .text("تعديل"),
            "delete":      .text("حذف"),

            // ورقة الإضافة/التعديل
            "addTitle":    .text("معلومة جديدة"),
            "editTitle":   .text("تعديل المعلومة"),
            "saveNew":     .text("احفظها"),
            "saveEdit":    .text("حفظ التعديل"),
            "sheet.prompt": .text("شو حابب ساندي تتذكّره عنك؟"),
            "sheet.placeholder": .text("مثلاً: بحب القهوة سادة، وعندي اجتماع كل اثنين…"),
        ],
        en: [
            "intro":       .text("Here's what Sandy remembers about you — add, edit, or delete anything."),
            "empty":       .text("Nothing saved about you yet — the more you talk, the more she knows."),
            "errorLoad":   .text("Couldn't load memory. Pull to refresh."),
            "errorDelete": .text("Couldn't delete. Try again."),
            "errorAdd":    .text("Couldn't save. Try again."),
            "errorEdit":   .text("Couldn't edit. Try again."),

            // row actions
            "add":         .text("Add memory"),
            "edit":        .text("Edit"),
            "delete":      .text("Delete"),

            // add/edit sheet
            "addTitle":    .text("New memory"),
            "editTitle":   .text("Edit memory"),
            "saveNew":     .text("Save it"),
            "saveEdit":    .text("Save changes"),
            "sheet.prompt": .text("What would you like Sandy to remember about you?"),
            "sheet.placeholder": .text("e.g. I like my coffee black, I have a meeting every Monday…"),
        ]
    )
}
