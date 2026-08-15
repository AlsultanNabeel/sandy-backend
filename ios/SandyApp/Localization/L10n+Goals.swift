import Foundation

// Namespace: goals — the Goals screen. The goals Sandy tracks for you (the same
// store her goal tools write to), over /api/goals: set, edit, mark done, drop.
enum L10nGoals {
    static let ns = "goals"

    static let table = L10nTable(
        ar: [
            "title":            .text("أهدافي"),
            "intro":            .text("الأهداف اللي قاعدة أتابعك عليها — حدّثها وقت ما تحب وأنا معك."),
            "add":              .text("هدف جديد"),
            "edit":             .text("تعديل"),
            "delete":           .text("حذف"),
            "markDone":         .text("خلّصته"),
            "reopen":           .text("رجّعه نشط"),
            "empty":            .text("لا توجد أهداف بعد — ما الذي تريد تحقيقه؟"),
            "section.active":   .text("نشطة"),
            "section.done":     .text("مكتملة"),
            "deadlinePrefix":   .text("الموعد: "),
            "addTitle":         .text("هدف جديد"),
            "editTitle":        .text("تعديل الهدف"),
            "saveNew":          .text("سجّل الهدف"),
            "saveEdit":         .text("حفظ التعديل"),
            "sheet.prompt":     .text("شو الهدف اللي تبي تحققه؟"),
            "sheet.placeholder": .text("مثال: أقرأ كتاب بالشهر"),
            "sheet.deadline":   .text("الموعد النهائي (اختياري)"),
            "sheet.deadlineHint": .text("مثال: 2026-09-01"),
            "errorLoad":        .text("تعذّر تحميل أهدافك. أعد المحاولة."),
            "errorAdd":         .text("تعذّر تسجيل الهدف. أعد المحاولة."),
            "errorEdit":        .text("تعذّر حفظ التعديل. أعد المحاولة."),
            "errorDelete":      .text("تعذّر حذف الهدف. أعد المحاولة."),
        ],
        en: [
            "title":            .text("Goals"),
            "intro":            .text("The goals I'm keeping you on track with — update them whenever you like, I'm with you."),
            "add":              .text("New goal"),
            "edit":             .text("Edit"),
            "delete":           .text("Delete"),
            "markDone":         .text("Done"),
            "reopen":           .text("Reopen"),
            "empty":            .text("No goals yet — what would you like to achieve?"),
            "section.active":   .text("Active"),
            "section.done":     .text("Completed"),
            "deadlinePrefix":   .text("Due: "),
            "addTitle":         .text("New goal"),
            "editTitle":        .text("Edit goal"),
            "saveNew":          .text("Set goal"),
            "saveEdit":         .text("Save changes"),
            "sheet.prompt":     .text("What goal do you want to reach?"),
            "sheet.placeholder": .text("e.g. Read a book each month"),
            "sheet.deadline":   .text("Deadline (optional)"),
            "sheet.deadlineHint": .text("e.g. 2026-09-01"),
            "errorLoad":        .text("Couldn't load your goals. Try again."),
            "errorAdd":         .text("Couldn't set the goal. Try again."),
            "errorEdit":        .text("Couldn't save the change. Try again."),
            "errorDelete":      .text("Couldn't delete the goal. Try again."),
        ]
    )
}
