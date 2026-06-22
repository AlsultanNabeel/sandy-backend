import Foundation

// Namespace: focus — the Focus tab (pomodoro timer + room scenes + stats).
// Mirrors the web studio.focus.* keys. Room control lives here (apply a scene
// → publishes room/cmd/* to the room-node over MQTT).
enum L10nFocus {
    static let ns = "focus"

    static let table = L10nTable(
        ar: [
            // أقسام فرعية
            "sub.timer":  .text("المؤقّت"),
            "sub.scenes": .text("المشاهد"),
            "sub.stats":  .text("إحصائيات"),

            // المؤقّت
            "timer.start":       .text("ابدأ"),
            "timer.finish":      .text("خلّصت"),
            "timer.cancel":      .text("إلغاء"),
            "timer.focusMin":    .text("تركيز (دق)"),
            "timer.breakMin":    .text("راحة (دق)"),
            "timer.cycles":      .text("دورات"),
            "timer.scene":       .text("مشهد البداية"),
            "timer.endScene":    .text("مشهد النهاية"),
            "timer.noScene":     .text("بدون مشهد"),
            "timer.label":       .text("على شو بتركّز؟"),
            "timer.labelPlaceholder": .text("مثلاً: مذاكرة فيزياء"),
            "timer.phaseFocus":  .text("تركيز"),
            "timer.phaseBreak":  .text("راحة"),
            "timer.cycle":       .text("دورة"),
            "timer.alreadyActive": .text("في جلسة شغّالة هلأ."),
            "timer.startError":  .text("معلش، ما قدرت أبدأ الجلسة — جرّب كمان مرة."),
            "timer.stopError":   .text("معلش، ما قدرت أوقّف الجلسة."),

            // المشاهد (تحكّم الغرفة)
            "scenes.apply":         .text("شغّل"),
            "scenes.applied":       .text("تمام — أرسلتها للغرفة 🏠"),
            "scenes.appliedOffline": .text("حفظت المشهد، بس الغرفة مش متّصلة."),
            "scenes.applyError":    .text("معلش، ما قدرت أطبّق المشهد."),
            "scenes.add":           .text("مشهد جديد"),
            "scenes.delete":        .text("حذف"),
            "scenes.edit":          .text("تعديل"),
            "scenes.save":          .text("حفظ"),
            "scenes.addAction":     .text("إضافة جهاز"),
            "scenes.namePlaceholder":  .text("اسم مختصر (إنجليزي)"),
            "scenes.labelPlaceholder": .text("الاسم الظاهر"),
            "scenes.empty":         .text("ما في مشاهد بعد — أضف وحدة."),
            "scenes.nameExists":    .text("في مشهد بنفس الاسم."),
            "scenes.builtinDel":    .text("هاد مشهد جاهز ما بينحذف."),
            "scenes.saveError":     .text("معلش، ما قدرت أحفظ المشهد."),

            // إحصائيات
            "stats.historyTitle": .text("آخر الجلسات"),
            "stats.noHistory":    .text("ما في جلسات بعد."),
            "stats.min":          .text("دقيقة"),
            "stats.cancelled":    .text("ملغاة"),

            "loadError": .text("معلش، ما قدرت أجيب الفوكس — اسحب للتحديث."),
        ],
        en: [
            "sub.timer":  .text("Timer"),
            "sub.scenes": .text("Scenes"),
            "sub.stats":  .text("Stats"),

            "timer.start":       .text("Start"),
            "timer.finish":      .text("Done"),
            "timer.cancel":      .text("Cancel"),
            "timer.focusMin":    .text("Focus (min)"),
            "timer.breakMin":    .text("Break (min)"),
            "timer.cycles":      .text("Cycles"),
            "timer.scene":       .text("Start scene"),
            "timer.endScene":    .text("End scene"),
            "timer.noScene":     .text("No scene"),
            "timer.label":       .text("What are you focusing on?"),
            "timer.labelPlaceholder": .text("e.g. Physics study"),
            "timer.phaseFocus":  .text("Focus"),
            "timer.phaseBreak":  .text("Break"),
            "timer.cycle":       .text("Cycle"),
            "timer.alreadyActive": .text("A session is already running."),
            "timer.startError":  .text("Sorry, I couldn't start the session — try again."),
            "timer.stopError":   .text("Sorry, I couldn't stop the session."),

            "scenes.apply":         .text("Run"),
            "scenes.applied":       .text("Done — sent to the room 🏠"),
            "scenes.appliedOffline": .text("Saved the scene, but the room is offline."),
            "scenes.applyError":    .text("Sorry, I couldn't apply the scene."),
            "scenes.add":           .text("New scene"),
            "scenes.delete":        .text("Delete"),
            "scenes.edit":          .text("Edit"),
            "scenes.save":          .text("Save"),
            "scenes.addAction":     .text("Add device"),
            "scenes.namePlaceholder":  .text("Short name (English)"),
            "scenes.labelPlaceholder": .text("Display name"),
            "scenes.empty":         .text("No scenes yet — add one."),
            "scenes.nameExists":    .text("A scene with that name exists."),
            "scenes.builtinDel":    .text("This is a built-in scene; it can't be deleted."),
            "scenes.saveError":     .text("Sorry, I couldn't save the scene."),

            "stats.historyTitle": .text("Recent sessions"),
            "stats.noHistory":    .text("No sessions yet."),
            "stats.min":          .text("min"),
            "stats.cancelled":    .text("cancelled"),

            "loadError": .text("Sorry, I couldn't load Focus — pull to refresh."),
        ]
    )
}
