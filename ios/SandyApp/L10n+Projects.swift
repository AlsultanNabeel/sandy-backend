import Foundation

// Namespace: projects — the Projects/Brainstorm archive screen. Full lifecycle:
// start a session, add ideas, finish (synthesize a plan) or cancel; edit/delete
// saved plans. Backed by /api/plans*.
enum L10nProjects {
    static let ns = "projects"

    static let table = L10nTable(
        ar: [
            "intro": .text("خطط العصف الذهني اللي خلّصتها ساندي — والجلسة الحالية إذا في وحدة شغّالة."),
            "empty": .text("لسّا ما في خطط محفوظة. ابدأ عصف ذهني جديد لأي فكرة."),
            "untitled": .text("بلا عنوان"),

            "errorLoad":   .text("معلش، ما قدرت أجيب المشاريع — اسحب للتحديث."),
            "errorStart":  .text("معلش، ما قدرت أبدأ الجلسة — جرّب كمان مرة."),
            "errorAdd":    .text("معلش، ما قدرت أضيف الفكرة — جرّب كمان مرة."),
            "errorFinish": .text("معلش، ما قدرت أخلّص الخطة — جرّب كمان مرة."),
            "errorCancel": .text("معلش، ما قدرت ألغي الجلسة — جرّب كمان مرة."),
            "errorUpdate": .text("معلش، ما قدرت أعدّل الخطة — جرّب كمان مرة."),
            "errorDelete": .text("معلش، ما قدرت أحذف الخطة — جرّب كمان مرة."),

            // بدء جلسة جديدة
            "start":         .text("عصف ذهني جديد"),
            "startTitle":    .text("عن شو الجلسة؟"),
            "startPlaceholder": .text("مثلاً: تخطيط رحلة، فكرة مشروع، تنظيم أسبوعي…"),
            "startAction":   .text("ابدأ"),

            // الجلسة النشطة
            "activeTitle":   .text("جلسة شغّالة"),
            "pointsEmpty":   .text("لسّا ما ضفت أفكار — اكتب أول وحدة تحت."),
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
            "empty": .text("No saved plans yet. Start a new brainstorm for any idea."),
            "untitled": .text("Untitled"),

            "errorLoad":   .text("Sorry, I couldn't load your projects — pull to refresh."),
            "errorStart":  .text("Sorry, I couldn't start the session — try again."),
            "errorAdd":    .text("Sorry, I couldn't add that idea — try again."),
            "errorFinish": .text("Sorry, I couldn't finish the plan — try again."),
            "errorCancel": .text("Sorry, I couldn't cancel the session — try again."),
            "errorUpdate": .text("Sorry, I couldn't update the plan — try again."),
            "errorDelete": .text("Sorry, I couldn't delete the plan — try again."),

            "start":         .text("New brainstorm"),
            "startTitle":    .text("What's the session about?"),
            "startPlaceholder": .text("e.g. trip planning, a project idea, weekly organizing…"),
            "startAction":   .text("Start"),

            "activeTitle":   .text("Active session"),
            "pointsEmpty":   .text("No ideas yet — type the first one below."),
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
