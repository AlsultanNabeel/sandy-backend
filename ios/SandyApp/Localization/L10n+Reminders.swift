import Foundation

// Namespace: reminders — the reminders screen (RemindersView + AddReminderSheet).
// Mirrors the web dict/<ns>.js shape (kept flat). FILLED by the migration.
//
// Usage:  Text(lang.s("reminders.add"))
//         Text(String(format: lang.s("reminders.relativeSep"), a, b))  // %@ format keys
enum L10nReminders {
    static let ns = "reminders"

    static let table = L10nTable(
        ar: [
            // Screen + add button
            "title":        .text("تذكيراتي"),
            "add":          .text("إضافة تذكير"),

            // Empty state
            "emptyTitle":   .text("ما في تذكيرات لسّا"),
            "emptyHint":    .text("خلّيني أنا أتذكّر عنك — أضف أول تذكير وأنا أنبّهك بوقته."),

            // Row
            "recurring":    .text("يتكرّر"),

            // إجراءات الصف (قائمة سياقية + سحب)
            "edit":         .text("تعديل"),
            "delete":       .text("حذف"),

            // Add/edit sheet
            "sheetTitle":   .text("تذكير جديد"),
            "editTitle":    .text("تعديل التذكير"),
            "sheetHeader":  .text("شو حابب أذكّرك فيه؟"),
            "textField":    .text("التذكير"),
            "textPlaceholder": .text("اكتب التذكير هنا…"),
            "timeField":    .text("الوقت"),
            "noteField":    .text("ملاحظة (اختياري)"),
            "notePlaceholder": .text("أي تفصيل إضافي… (اختياري)"),
            "submit":       .text("تذكّرني"),
            "saveEdit":     .text("حفظ التعديل"),

            // Sandy-voice notices
            "loadFailed":   .text("معلش، ما قدرت أجيب تذكيراتك هلّق. اسحب لتحت تنعش الصفحة وأنا أحاول من جديد."),
            "pastGuard":    .text("الوقت اللي اخترته راح خلص. خليه ولو بعد دقيقتين من هلّق وأنا أتكفّل."),
            "savePast":     .text("يبدو إن الوقت صار بالماضي. خلّيه شوي بعد هلّق وأنا أذكّرك فيه."),
            "saveFailed":   .text("معلش، ما زبط الحفظ هلّق. جرّب كمان مرة بعد لحظة وأنا معك."),
        ],
        en: [
            // Screen + add button
            "title":        .text("My Reminders"),
            "add":          .text("Add reminder"),

            // Empty state
            "emptyTitle":   .text("No reminders yet"),
            "emptyHint":    .text("Let me remember for you — add your first reminder and I'll nudge you when it's time."),

            // Row
            "recurring":    .text("Repeats"),

            // row actions (context menu + swipe)
            "edit":         .text("Edit"),
            "delete":       .text("Delete"),

            // Add/edit sheet
            "sheetTitle":   .text("New reminder"),
            "editTitle":    .text("Edit reminder"),
            "sheetHeader":  .text("What should I remind you about?"),
            "textField":    .text("Reminder"),
            "textPlaceholder": .text("Type the reminder here…"),
            "timeField":    .text("Time"),
            "noteField":    .text("Note (optional)"),
            "notePlaceholder": .text("Any extra detail… (optional)"),
            "submit":       .text("Remind me"),
            "saveEdit":     .text("Save changes"),

            // Sandy-voice notices
            "loadFailed":   .text("Sorry, I couldn't fetch your reminders right now. Pull down to refresh and I'll try again."),
            "pastGuard":    .text("The time you picked has already passed. Set it at least a couple minutes from now and I've got you."),
            "savePast":     .text("Looks like that time is already in the past. Set it a little after now and I'll remind you."),
            "saveFailed":   .text("Sorry, that didn't save just now. Give it another try in a moment — I'm with you."),
        ]
    )
}
