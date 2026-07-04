import Foundation

// Namespace: widgets — the iPhone-style customizable widget board (WidgetDashboard).
enum L10nWidgets {
    static let ns = "widgets"

    static let table = L10nTable(
        ar: [
            "size.small":     .text("صغير"),
            "size.medium":    .text("وسط"),
            "size.large":     .text("كبير"),
            "gallery.title":  .text("إضافة ويدجت"),
            "gallery.empty":  .text("كل الويدجتات مضافة"),
        ],
        en: [
            "size.small":     .text("Small"),
            "size.medium":    .text("Medium"),
            "size.large":     .text("Large"),
            "gallery.title":  .text("Add Widget"),
            "gallery.empty":  .text("All widgets are added"),
        ]
    )
}
