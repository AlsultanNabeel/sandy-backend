import Foundation

// Namespace: life — the My Life tab (the log). Everything else it shows comes from blocks.
enum L10nLife {
    static let ns = "life"

    static let table = L10nTable(
        ar: [
            "title": .text("حياتي"),
            "month": .text("شهرك"),
            "showAll": .text("رجّع كل الأيام"),
            "budget.limit": .text("ميزانية الشهر"),
            "budget.none": .text("بدون حد"),
            "budget.used": .text("صرفت %@ من %@"),
            "budget.where": .text("وين راحت المصاري"),
            "budget.empty": .text("لسا ما صرفت إشي هالشهر."),
            "budget.title": .text("ميزانية الشهر 💸"),
            "budget.near": .text("صرفت %@ من %@ هالشهر، قرّبت توصل الحد."),
            "budget.over": .text("صرفت %@ وميزانيتك %@، تعدّيت الحد هالشهر."),
            "stat.spent": .text("صرفت هالشهر"),
            "stat.habits": .text("مرة التزمت"),
            "stat.logged": .text("إشي سجّلت"),
        ],
        en: [
            "title": .text("My Life"),
            "month": .text("Your month"),
            "showAll": .text("Show all days"),
            "budget.limit": .text("Monthly budget"),
            "budget.none": .text("No limit"),
            "budget.used": .text("Spent %@ of %@"),
            "budget.where": .text("Where it went"),
            "budget.empty": .text("Nothing spent this month yet."),
            "budget.title": .text("Monthly budget 💸"),
            "budget.near": .text("You've spent %@ of %@ this month, close to the limit."),
            "budget.over": .text("You've spent %@ and your budget is %@: over the limit this month."),
            "stat.spent": .text("Spent this month"),
            "stat.habits": .text("Habits kept"),
            "stat.logged": .text("Things logged"),
        ]
    )
}
