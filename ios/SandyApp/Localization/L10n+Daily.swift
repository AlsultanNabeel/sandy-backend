import Foundation

// Namespace: daily — the "يومي" tab. Its list cards take their names from the kinds
// table; only the fixed cards (focus, future messages) are named here.
enum L10nDaily {
    static let ns = "daily"

    static let table = L10nTable(
        ar: [
            "title":              .text("يومي"),
            "focus":              .text("الفوكس"),
            "future":             .text("رسالة لمستقبلك"),
        ],
        en: [
            "title":              .text("Daily"),
            "focus":              .text("Focus"),
            "future":             .text("Message to your future"),
        ]
    )
}
