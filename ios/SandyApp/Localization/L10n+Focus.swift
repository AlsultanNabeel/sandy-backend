import Foundation

// Namespace: focus — the Focus tab (pomodoro timer + stats). Mirrors the web
// studio.focus.* keys. The timer can bind a start/end room scene, so it keeps the
// timer.scene/endScene/noScene keys; scene management itself moved to the Robot
// tab (L10n+Robot.swift).
enum L10nFocus {
    static let ns = "focus"

    static let table = L10nTable(
        ar: [
            // أقسام فرعية
            "sub.timer":  .text("المؤقّت"),
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

            // إحصائيات
            "stats.historyTitle": .text("آخر الجلسات"),
            "stats.noHistory":    .text("ما في جلسات بعد."),
            "stats.min":          .text("دقيقة"),
            "stats.cancelled":    .text("ملغاة"),

            "loadError": .text("معلش، ما قدرت أجيب الفوكس — اسحب للتحديث."),
        ],
        en: [
            "sub.timer":  .text("Timer"),
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

            "stats.historyTitle": .text("Recent sessions"),
            "stats.noHistory":    .text("No sessions yet."),
            "stats.min":          .text("min"),
            "stats.cancelled":    .text("cancelled"),

            "loadError": .text("Sorry, I couldn't load Focus — pull to refresh."),
        ]
    )
}
