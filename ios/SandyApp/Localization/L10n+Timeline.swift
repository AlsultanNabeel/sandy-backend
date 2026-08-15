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

            "empty":       .text("لا يوجد نشاط بعد — كلما استخدمت ساندي، امتلأ هذا الخط."),
            "errorLoad":   .text("تعذّر تحميل الخط الزمني. اسحب للتحديث."),
            "errorDelete": .text("تعذّر الحذف. أعد المحاولة."),
            "errorToggle": .text("تعذّر تحديث المهمة. أعد المحاولة."),

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

            "empty":       .text("No activity yet — this fills up as you use Sandy."),
            "errorLoad":   .text("Couldn't load your timeline. Pull to refresh."),
            "errorDelete": .text("Couldn't delete. Try again."),
            "errorToggle": .text("Couldn't update the task. Try again."),

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
