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
        ]
    )
}
