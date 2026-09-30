import Foundation

// Namespace: sandy — the unified AI hub tab. Chat is the primary surface (the
// engine that does everything), with search and image-generation one tap away
// via a top mode switcher. Mirrors the product blueprint's "Unified AI Hub".
enum L10nSandy {
    static let ns = "sandy"

    static let table = L10nTable(
        ar: [
            "mode.chat":   .text("محادثة"),
            "mode.search": .text("بحث"),
            "mode.images": .text("صور"),
            "tools":       .text("أدوات ساندي"),
            "photos":      .text("الألبوم"),
            "companion.name":  .text("ساندي"),
            "companion.hint":  .text("يفتح المحادثة مع ساندي"),
            "companion.home":  .text("أهلاً بك، أنا هنا متى احتجتني."),
            "companion.sandy": .text("تفضّل، أنا أسمعك."),
            "companion.daily": .text("نرتّب يومك معاً؟"),
            "companion.life":  .text("كيف حالك اليوم؟"),
        ],
        en: [
            "mode.chat":   .text("Chat"),
            "mode.search": .text("Search"),
            "mode.images": .text("Images"),
            "tools":       .text("Sandy's tools"),
            "photos":      .text("Album"),
            "companion.name":  .text("Sandy"),
            "companion.hint":  .text("Opens your chat with Sandy"),
            "companion.home":  .text("Welcome back. I'm here whenever you need me."),
            "companion.sandy": .text("Go ahead, I'm listening."),
            "companion.daily": .text("Shall we plan your day?"),
            "companion.life":  .text("How are you doing today?"),
        ]
    )
}
