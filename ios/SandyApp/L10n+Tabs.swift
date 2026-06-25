import Foundation

// Namespace: tabs — the five MainTabView titles. Mirrors the web navbar tab
// labels (kept flat). FILLED.
//
// Usage:  Label(lang.s("tabs.home"), systemImage: "house.fill")
enum L10nTabs {
    static let ns = "tabs"

    static let table = L10nTable(
        ar: [
            "home":      .text("الرئيسية"),
            "chat":      .text("ساندي"),
            "tasks":     .text("مهامي"),
            "reminders": .text("تذكيراتي"),
            "life":      .text("حياتي"),
            "focus":     .text("الفوكس"),
            "room":      .text("الغرفة"),
            "robot":     .text("الروبوت"),
            "search":    .text("البحث"),
            "images":    .text("الصور"),
            "emails":    .text("الإيميلات"),
        ],
        en: [
            "home":      .text("Home"),
            "chat":      .text("Sandy"),
            "tasks":     .text("Tasks"),
            "reminders": .text("Reminders"),
            "life":      .text("Life"),
            "focus":     .text("Focus"),
            "room":      .text("Room"),
            "robot":     .text("Robot"),
            "search":    .text("Search"),
            "images":    .text("Images"),
            "emails":    .text("Emails"),
        ]
    )
}
