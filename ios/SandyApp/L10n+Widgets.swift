import Foundation

// Namespace: widgets — the customizable per-tab widget grid (WidgetDashboard).
enum L10nWidgets {
    static let ns = "widgets"

    static let table = L10nTable(
        ar: [
            "edit":  .text("ترتيب"),
            "hint":  .text("اسحب لترتيب، − لإخفاء، ⤢ لتكبير"),
        ],
        en: [
            "edit":  .text("Edit"),
            "hint":  .text("Drag to reorder, − to hide, ⤢ to resize"),
        ]
    )
}
