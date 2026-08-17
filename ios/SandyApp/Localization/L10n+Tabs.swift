import Foundation

// Namespace: tabs — the four Core-4 navigation titles (الرئيسية/ساندي/يومي/حياتي)
// plus the titles of the feature screens that are now reached from inside a hub
// or the profile archive (search/images/memory/timeline/projects/robot/focus) —
// each of those screens still uses its `tabs.*` key as its own navigationTitle.
//
// Usage:  Label(lang.s("tabs.home"), systemImage: "house.fill")
enum L10nTabs {
    static let ns = "tabs"

    static let table = L10nTable(
        ar: [
            // الشريط السفلي — أربعة تبويبات.
            "home":     .text("الرئيسية"),
            "sandy":    .text("ساندي"),
            "daily":    .text("يومي"),
            "life":     .text("حياتي"),
            // عناوين شاشات الميزات (تُفتح من جوّا هَب أو من أرشيف البروفايل).
            "focus":    .text("الفوكس"),
            "robot":    .text("مشاهد الغرفة"),   // مش الروبوت: هاي سيناريوهات الأجهزة
            "search":   .text("البحث"),
            "images":   .text("الصور"),
            "memory":   .text("الذاكرة"),
            "timeline": .text("الخط الزمني"),
            "projects": .text("المشاريع"),
            "shareContent": .text("مشاركة"),
        ],
        en: [
            "home":     .text("Home"),
            "sandy":    .text("Sandy"),
            "daily":    .text("Daily"),
            "life":     .text("Life"),
            "focus":    .text("Focus"),
            "robot":    .text("Room scenes"),   // not the robot: these are device scenes
            "search":   .text("Search"),
            "images":   .text("Images"),
            "memory":   .text("Memory"),
            "timeline": .text("Timeline"),
            "projects": .text("Projects"),
            "shareContent": .text("Share"),
        ]
    )
}
