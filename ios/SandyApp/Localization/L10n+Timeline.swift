import Foundation

// Namespace: timeline — the Timeline tab (unified activity log). Aggregates the
// user's tasks/reminders/expenses/journal from /api/timeline.
enum L10nTimeline {
    static let ns = "timeline"

    static let table = L10nTable(
        ar: [
            "today":     .text("اليوم"),
            "yesterday": .text("أمس"),
            "week":      .text("آخر سبعة أيام"),
            "older":     .text("أقدم"),

            "type.task":     .text("مهمة"),
            "type.reminder": .text("تذكير"),
            "type.expense":  .text("مصروف"),
            "type.journal":  .text("يومية"),

            "empty":       .text("لسّا ما في نشاط — كل ما تستعمل ساندي، بينعبّى الخط هون."),
            "errorLoad":   .text("معلش، ما قدرت أجيب الخط الزمني — اسحب للتحديث."),
            "errorDelete": .text("معلش، ما قدرت أحذف — جرّب كمان مرة."),
            "errorToggle": .text("معلش، ما زبطت أحدّث المهمة — جرّب كمان مرة."),

            // إجراءات وتفاصيل
            "delete":         .text("حذف"),
            "markDone":       .text("علّمها منجزة"),
            "markUndone":     .text("رجّعها غير منجزة"),
            "detailsAction":  .text("التفاصيل"),
            "detailTitle":    .text("تفاصيل النشاط"),
            "detailHint":     .text("للتعديل التفصيلي، افتح العنصر من تبويبه المخصّص."),
        ],
        en: [
            "today":     .text("Today"),
            "yesterday": .text("Yesterday"),
            "week":      .text("Last 7 days"),
            "older":     .text("Older"),

            "type.task":     .text("Task"),
            "type.reminder": .text("Reminder"),
            "type.expense":  .text("Expense"),
            "type.journal":  .text("Journal"),

            "empty":       .text("No activity yet — as you use Sandy, it fills up here."),
            "errorLoad":   .text("Sorry, I couldn't load your timeline — pull to refresh."),
            "errorDelete": .text("Sorry, I couldn't delete that — try again."),
            "errorToggle": .text("Sorry, I couldn't update the task — give it another try."),

            // actions & details
            "delete":         .text("Delete"),
            "markDone":       .text("Mark done"),
            "markUndone":     .text("Mark not done"),
            "detailsAction":  .text("Details"),
            "detailTitle":    .text("Activity details"),
            "detailHint":     .text("For detailed editing, open the item from its own tab."),
        ]
    )
}
