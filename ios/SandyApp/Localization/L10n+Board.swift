import Foundation

// Namespace: board — arranging and resizing the cards on any screen.
enum L10nBoard {
    static let ns = "board"

    static let table = L10nTable(
        ar: [
            "edit":    .text("ظبّط الصفحة"),
            "done":    .text("خلصت"),
            "reset":   .text("رجّع الأصلي"),
            "resize":     .text("غيّر الحجم"),
            "size.small":  .text("مربّع"),
            "size.medium": .text("عريض"),
            "size.large":  .text("كبير"),
            "hint":    .text("اسحب البطاقة لمكانها · − و + للحجم"),
        ],
        en: [
            "edit":    .text("Arrange"),
            "done":    .text("Done"),
            "reset":   .text("Reset"),
            "resize":     .text("Resize"),
            "size.small":  .text("Square"),
            "size.medium": .text("Wide"),
            "size.large":  .text("Large"),
            "hint":    .text("Drag a card to move it · − and + to resize"),
        ]
    )
}
