import Foundation

// Namespace: board — arranging and resizing the cards on any screen.
enum L10nBoard {
    static let ns = "board"

    static let table = L10nTable(
        ar: [
            "edit":    .text("ظبّط الصفحة"),
            "done":    .text("خلصت"),
            "reset":   .text("رجّع الأصلي"),
            "resize":  .text("اسحب لتغيير الحجم"),
            "hint":    .text("اسحب البطاقة لمكانها · − و + للحجم · أو اقرص بإصبعين"),
        ],
        en: [
            "edit":    .text("Arrange"),
            "done":    .text("Done"),
            "reset":   .text("Reset"),
            "resize":  .text("Drag to resize"),
            "hint":    .text("Drag a card to move it · − and + to resize · or pinch"),
        ]
    )
}
