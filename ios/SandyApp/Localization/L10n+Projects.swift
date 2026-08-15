import Foundation

// Namespace: projects — the Projects/Brainstorm archive screen. Full lifecycle:
// start a session, add ideas, finish (synthesize a plan) or cancel; edit/delete
// saved plans. Backed by /api/plans*.
enum L10nProjects {
    static let ns = "projects"

    static let table = L10nTable(
        ar: [
            "intro": .text("خطط العصف الذهني اللي خلّصتها ساندي — والجلسة الحالية إذا في وحدة شغّالة."),
            "empty": .text("لا توجد خطط محفوظة. ابدأ جلسة عصف ذهني جديدة."),
            "untitled": .text("بلا عنوان"),

            "errorLoad":   .text("تعذّر تحميل المشاريع. اسحب للتحديث."),
            "errorStart":  .text("تعذّر بدء الجلسة. أعد المحاولة."),
            "errorAdd":    .text("تعذّرت إضافة الفكرة. أعد المحاولة."),
            "errorFinish": .text("تعذّر إنهاء الخطة. أعد المحاولة."),
            "errorCancel": .text("تعذّر إلغاء الجلسة. أعد المحاولة."),
            "errorUpdate": .text("تعذّر تعديل الخطة. أعد المحاولة."),
            "errorDelete": .text("تعذّر حذف الخطة. أعد المحاولة."),

            // بدء جلسة جديدة
            "start":         .text("عصف ذهني جديد"),
            "startTitle":    .text("عن شو الجلسة؟"),
            "startPlaceholder": .text("مثلاً: تخطيط رحلة، فكرة مشروع، تنظيم أسبوعي…"),
            "startAction":   .text("ابدأ"),

            // الجلسة النشطة
            "activeTitle":   .text("جلسة شغّالة"),
            "pointsEmpty":   .text("لم تُضِف أفكارًا بعد — اكتب أول فكرة في الأسفل."),
            "addPointPlaceholder": .text("أضف فكرة…"),
            "add":           .text("ضيف"),
            "finish":        .text("خلّص الخطة"),
            "cancel":        .text("إلغاء الجلسة"),
            "cancelConfirm": .text("متأكد بدك تلغي الجلسة؟ الأفكار يلي ضفتها بتضيع."),

            // تفاصيل خطة محفوظة
            "detailTitle": .text("تفاصيل الخطة"),
            "detailHint":  .text("عدّل الخطة بوصف التغيير اللي بدك إياه، وساندي بتحدّثها."),
            "edit":        .text("عدّل"),
            "editTitle":   .text("شو بدك تغيّر؟"),
            "editPlaceholder": .text("مثلاً: ضيف خطوة عن الميزانية، اختصر القسم الأخير…"),
            "editAction":  .text("حدّث الخطة"),
            "delete":      .text("حذف"),
            "deleteConfirm": .text("متأكد بدك تحذف هالخطة؟ ما في رجعة."),
        ],
        en: [
            "intro": .text("Brainstorm plans Sandy finished — plus your active session, if you have one."),
            "empty": .text("No saved plans. Start a new brainstorm."),
            "untitled": .text("Untitled"),

            "errorLoad":   .text("Couldn't load your projects. Pull to refresh."),
            "errorStart":  .text("Couldn't start the session. Try again."),
            "errorAdd":    .text("Couldn't add the idea. Try again."),
            "errorFinish": .text("Couldn't finish the plan. Try again."),
            "errorCancel": .text("Couldn't cancel the session. Try again."),
            "errorUpdate": .text("Couldn't update the plan. Try again."),
            "errorDelete": .text("Couldn't delete the plan. Try again."),

            "start":         .text("New brainstorm"),
            "startTitle":    .text("What's the session about?"),
            "startPlaceholder": .text("e.g. trip planning, a project idea, weekly organizing…"),
            "startAction":   .text("Start"),

            "activeTitle":   .text("Active session"),
            "pointsEmpty":   .text("No ideas yet — write your first one below."),
            "addPointPlaceholder": .text("Add an idea…"),
            "add":           .text("Add"),
            "finish":        .text("Finish plan"),
            "cancel":        .text("Cancel session"),
            "cancelConfirm": .text("Cancel this session? The ideas you added will be lost."),

            "detailTitle": .text("Plan details"),
            "detailHint":  .text("Describe the change you want, and Sandy will update the plan."),
            "edit":        .text("Edit"),
            "editTitle":   .text("What do you want to change?"),
            "editPlaceholder": .text("e.g. add a budget step, shorten the last section…"),
            "editAction":  .text("Update plan"),
            "delete":      .text("Delete"),
            "deleteConfirm": .text("Delete this plan? This can't be undone."),
        ]
    )
}
