import Foundation

// Namespace: life — the My Life tab (the log). Everything else it shows comes from blocks.
enum L10nLife {
    static let ns = "life"

    static let table = L10nTable(
        ar: [
            "title": .text("حياتي"),
        ],
        en: [
            "title": .text("My Life"),
        ]
    )
}
