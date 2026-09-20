import Foundation

// Namespace: insights — the weekly summary screen (/api/insights/weekly), its
// entry card on Daily, and the proactive local notifications that point to it
// (away nudge, heads-up before a due time, Sunday "your week is ready").
enum L10nInsights {
    static let ns = "insights"

    static let table = L10nTable(
        ar: [
            "title":          .text("ملخّص أسبوعك"),
            "card":           .text("ملخّص الأسبوع"),
            "card.subtitle":  .text("أرقامك هالأسبوع مقارنة بالماضي"),
            "range":          .text("آخر سبعة أيام مقارنة بالسبعة اللي قبلها"),
            "sandySays":      .text("ساندي بتقلّك"),
            "vsLast":         .text("الأسبوع الماضي: %@"),
            "same":           .text("متل الأسبوع الماضي"),
            "new":            .text("جديد هالأسبوع"),
            "bestStreak":     .text("أطول سلسلة عادة"),
            "days":           .text("%@ يوم"),
            "demo":           .text("هاي أرقام تجريبية — سجّل دخولك لتشوف أسبوعك."),
            "errorLoad":      .text("ما قدرت أجيب ملخّص أسبوعك هلّق. اسحب للتحديث."),

            "metric.tasks_completed":  .text("مهام منجزة"),
            "metric.reminders_done":   .text("تذكيرات"),
            "metric.focus_minutes":    .text("دقائق تركيز"),
            "metric.habit_checkins":   .text("تسجيلات العادات"),
            "metric.expenses_total":   .text("المصاريف"),
            "metric.journal_entries":  .text("تدوينات اليوميات"),
            "metric.reading_pages":    .text("صفحات قرأتها"),
            "metric.reading_sessions": .text("جلسات قراءة"),
            "metric.chat_turns":       .text("رسائلك لساندي"),

            // إشعارات محلية استباقية
            "notif.away.title":     .text("ساندي"),
            "notif.away.body":      .text("صارلك يومين ما حكيتني… اشتقتلك. كيفك؟"),
            "notif.headsUp.title":  .text("بعد ساعة"),
            "notif.headsUp.body":   .text("تذكير لطيف: «%@» بعد ساعة من هلّق."),
            "notif.weekly.title":   .text("ملخّص أسبوعك جاهز"),
            "notif.weekly.body":    .text("تعال شوف شو عملت هالأسبوع — عندي كلمة إلك."),
        ],
        en: [
            "title":          .text("Your week"),
            "card":           .text("Weekly summary"),
            "card.subtitle":  .text("This week's numbers next to last week's"),
            "range":          .text("Last 7 days compared with the 7 before"),
            "sandySays":      .text("Sandy says"),
            "vsLast":         .text("Last week: %@"),
            "same":           .text("Same as last week"),
            "new":            .text("New this week"),
            "bestStreak":     .text("Longest habit streak"),
            "days":           .text("%@ days"),
            "demo":           .text("These are sample numbers — sign in to see your week."),
            "errorLoad":      .text("I couldn't load your weekly summary right now. Pull to refresh."),

            "metric.tasks_completed":  .text("Tasks done"),
            "metric.reminders_done":   .text("Reminders"),
            "metric.focus_minutes":    .text("Focus minutes"),
            "metric.habit_checkins":   .text("Habit check-ins"),
            "metric.expenses_total":   .text("Spending"),
            "metric.journal_entries":  .text("Journal entries"),
            "metric.reading_pages":    .text("Pages read"),
            "metric.reading_sessions": .text("Reading sessions"),
            "metric.chat_turns":       .text("Messages to Sandy"),

            "notif.away.title":     .text("Sandy"),
            "notif.away.body":      .text("It's been two days since we talked… I miss you. How are you?"),
            "notif.headsUp.title":  .text("In an hour"),
            "notif.headsUp.body":   .text("A gentle heads-up: “%@” is an hour from now."),
            "notif.weekly.title":   .text("Your weekly summary is ready"),
            "notif.weekly.body":    .text("Come see what you did this week — I have a word for you."),
        ]
    )
}
