import Foundation

// Namespace: memory — the Memory tab (what Sandy remembers about you). Real facts
// from /api/memory; excludes Sandy's internal/system memory.
enum L10nMemory {
    static let ns = "memory"

    static let table = L10nTable(
        ar: [
            "intro":       .text("هاي المعلومات اللي ساندي متذكّراها عنك — تقدر تضيف أو تعدّل أو تحذف أي وحدة."),
            "empty":       .text("لسّا ما ساندي حفظت إشي عنك — كل ما تحكوا أكثر، بتعرفك أكثر."),
            "errorLoad":   .text("معلش، ما قدرت أجيب الذاكرة — اسحب للتحديث."),
            "errorDelete": .text("معلش، ما قدرت أحذف — جرّب كمان مرة."),
            "errorAdd":    .text("معلش، ما قدرت أحفظ المعلومة — جرّب كمان مرة."),
            "errorEdit":   .text("معلش، ما قدرت أعدّل المعلومة — جرّب كمان مرة."),

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
            "empty":       .text("Sandy hasn't saved anything about you yet — the more you chat, the better she knows you."),
            "errorLoad":   .text("Sorry, I couldn't load your memory — pull to refresh."),
            "errorDelete": .text("Sorry, I couldn't delete that — try again."),
            "errorAdd":    .text("Sorry, I couldn't save that — give it another try."),
            "errorEdit":   .text("Sorry, I couldn't update that — give it another try."),

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
