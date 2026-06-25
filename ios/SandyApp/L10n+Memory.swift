import Foundation

// Namespace: memory — the Memory tab (what Sandy remembers about you). Real facts
// from /api/memory; excludes Sandy's internal/system memory.
enum L10nMemory {
    static let ns = "memory"

    static let table = L10nTable(
        ar: [
            "intro":       .text("هاي المعلومات اللي ساندي متذكّراها عنك — تقدر تحذف أي وحدة."),
            "empty":       .text("لسّا ما ساندي حفظت إشي عنك — كل ما تحكوا أكثر، بتعرفك أكثر."),
            "errorLoad":   .text("معلش، ما قدرت أجيب الذاكرة — اسحب للتحديث."),
            "errorDelete": .text("معلش، ما قدرت أحذف — جرّب كمان مرة."),
        ],
        en: [
            "intro":       .text("Here's what Sandy remembers about you — delete anything you want."),
            "empty":       .text("Sandy hasn't saved anything about you yet — the more you chat, the better she knows you."),
            "errorLoad":   .text("Sorry, I couldn't load your memory — pull to refresh."),
            "errorDelete": .text("Sorry, I couldn't delete that — try again."),
        ]
    )
}
