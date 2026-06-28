import Foundation

// Namespace: daily — the "يومي" planner tab. A hub of day-to-day screens (tasks,
// reminders, habits, focus); goals + scheduled-messages join later. Mirrors the
// LifeView hub-of-cards pattern (each row pushes a full screen).
enum L10nDaily {
    static let ns = "daily"

    static let table = L10nTable(
        ar: [
            "title":              .text("يومي"),
            "tasks":              .text("مهامي"),
            "tasks.subtitle":     .text("كل اللي لازم تخلّصه"),
            "reminders":          .text("تذكيراتي"),
            "reminders.subtitle": .text("ساندي بتذكّرك بكل شي"),
            "habits":             .text("العادات"),
            "habits.subtitle":    .text("سلاسلك اليومية وتقدّمك"),
            "focus":              .text("الفوكس"),
            "focus.subtitle":     .text("مؤقّت تركيز وإحصائياتك"),
        ],
        en: [
            "title":              .text("Daily"),
            "tasks":              .text("Tasks"),
            "tasks.subtitle":     .text("Everything you need to finish"),
            "reminders":          .text("Reminders"),
            "reminders.subtitle": .text("Sandy keeps you on track"),
            "habits":             .text("Habits"),
            "habits.subtitle":    .text("Your daily streaks and progress"),
            "focus":              .text("Focus"),
            "focus.subtitle":     .text("Focus timer and your stats"),
        ]
    )
}
