import Foundation

// Namespace: tasks — the tasks screen. Filled by the TasksView migration.
// Mirrors the web dict/<ns>.js shape (flat keys, ar + en). Backend raw values
// for priority ("low"/"normal"/"high") are NOT here — only their visible labels.
//
// Usage:  Text(lang.s("tasks.add"))   /   lang.list("tasks.…") for arrays
enum L10nTasks {
    static let ns = "tasks"

    static let table = L10nTable(
        ar: [
            "title": .text("مهامي"),
            "add":   .text("إضافة مهمة"),
            "empty": .text("ما في مهام بعد"),

            // فلتر نشطة/مكتملة
            "filterActive":    .text("نشطة"),
            "filterCompleted": .text("مكتملة"),
            "emptyCompleted":  .text("ما خلّصت أي مهمة بعد — يلا نبلش!"),

            // حالة التحميل
            "loadingLine": .text("لحظة، بجيب مهامك…"),

            // حالة فاضية (تشجيعية)
            "emptyTitle":    .text("صفحة بيضا!"),
            "emptySubtitle": .text("ما في مهام لسّا — خلّينا نبدأ بوحدة صغيرة."),

            // تنبيهات ودّية (أخطاء)
            "errorLoad":   .text("معلش، ما قدرت أجيب مهامك — جرّب تسحب للتحديث كمان مرة."),
            "errorAdd":    .text("معلش، ما قدرت أضيف المهمة — جرّب كمان مرة."),
            "errorToggle": .text("معلش، ما زبطت أحدّث المهمة — جرّب كمان مرة."),
            "errorDelete": .text("معلش، ما قدرت أحذف المهمة — جرّب كمان مرة."),
            "errorEdit":   .text("معلش، ما قدرت أعدّل المهمة — جرّب كمان مرة."),

            // القائمة السياقية وإيماءات السحب
            "markDone":   .text("تعليم كمنجزة"),
            "markUndone": .text("رجّعها غير منجزة"),
            "edit":       .text("تعديل"),
            "delete":     .text("حذف"),

            // شارات الأولوية (التسميات المرئية فقط)
            "priorityHigh":   .text("عالية"),
            "priorityNormal": .text("عادية"),
            "priorityLow":    .text("منخفضة"),

            // ورقة الإضافة/التعديل
            "newTask":         .text("مهمة جديدة"),
            "editTask":        .text("تعديل المهمة"),
            "saveTask":        .text("حفظ المهمة"),
            "saveEdit":        .text("حفظ التعديل"),
            "titleQuestion":   .text("شو المهمة؟"),
            "titlePlaceholder": .text("مثلاً: أكمّل تقرير المشروع"),
            "priority":        .text("الأولوية"),
            "dueToggle":       .text("في موعد؟"),
            "dueDate":         .text("الموعد"),
            "noteHeader":      .text("ملاحظة (اختياري)"),
            "notePlaceholder": .text("تفاصيل إضافية لو حابب…"),
        ],
        en: [
            "title": .text("My Tasks"),
            "add":   .text("Add task"),
            "empty": .text("No tasks yet"),

            // active/completed filter
            "filterActive":    .text("Active"),
            "filterCompleted": .text("Completed"),
            "emptyCompleted":  .text("Nothing finished yet — let's get going!"),

            // loading state
            "loadingLine": .text("One sec, grabbing your tasks…"),

            // empty state (encouraging)
            "emptyTitle":    .text("Clean slate!"),
            "emptySubtitle": .text("No tasks yet — let's start with one small thing."),

            // friendly error notices
            "errorLoad":   .text("Sorry, I couldn't load your tasks — pull to refresh and try again."),
            "errorAdd":    .text("Sorry, I couldn't add the task — give it another try."),
            "errorToggle": .text("Sorry, I couldn't update the task — give it another try."),
            "errorDelete": .text("Sorry, I couldn't delete the task — give it another try."),
            "errorEdit":   .text("Sorry, I couldn't update the task — give it another try."),

            // context menu & swipe actions
            "markDone":   .text("Mark done"),
            "markUndone": .text("Mark not done"),
            "edit":       .text("Edit"),
            "delete":     .text("Delete"),

            // priority badges (visible labels only)
            "priorityHigh":   .text("High"),
            "priorityNormal": .text("Normal"),
            "priorityLow":    .text("Low"),

            // add/edit sheet
            "newTask":         .text("New task"),
            "editTask":        .text("Edit task"),
            "saveTask":        .text("Save task"),
            "saveEdit":        .text("Save changes"),
            "titleQuestion":   .text("What's the task?"),
            "titlePlaceholder": .text("e.g. Finish the project report"),
            "priority":        .text("Priority"),
            "dueToggle":       .text("Has a due date?"),
            "dueDate":         .text("Due"),
            "noteHeader":      .text("Note (optional)"),
            "notePlaceholder": .text("Extra details if you like…"),
        ]
    )
}
