import Foundation

// Namespace: nudge — the daily-nudge card on Home (DailyNudgeCard). Phase 7.
// A question every other day (build the profile gradually) or an LLM-written
// agenda line in Sandy's voice on the days between. FILLED.
enum L10nNudge {
    static let ns = "nudge"

    static let table = L10nTable(
        ar: [
            "title":              .text("تنبيه اليوم"),
            "answer.placeholder": .text("جوابك…"),
            "answer.send":        .text("أرسل"),
            "answered":           .text("تمام، سجّلتها 🌿"),
            "dismiss":            .text("تمام"),
        ],
        en: [
            "title":              .text("Today"),
            "answer.placeholder": .text("Your answer…"),
            "answer.send":        .text("Send"),
            "answered":           .text("Got it, saved 🌿"),
            "dismiss":            .text("Got it"),
        ]
    )
}
