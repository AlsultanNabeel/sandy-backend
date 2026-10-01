import Foundation

// Namespace: life — the My Life tab (the log). Everything else it shows comes from blocks.
enum L10nLife {
    static let ns = "life"

    static let table = L10nTable(
        ar: [
            "title": .text("حياتي"),
            "month": .text("شهرك"),
            "showAll": .text("رجّع كل الأيام"),
            "stat.spent": .text("صرفت هالشهر"),
            "stat.habits": .text("مرة التزمت"),
            "stat.logged": .text("إشي سجّلت"),
        ],
        en: [
            "title": .text("My Life"),
            "month": .text("Your month"),
            "showAll": .text("Show all days"),
            "stat.spent": .text("Spent this month"),
            "stat.habits": .text("Habits kept"),
            "stat.logged": .text("Things logged"),
        ]
    )
}
