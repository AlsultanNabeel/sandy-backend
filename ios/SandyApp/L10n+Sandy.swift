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
        ],
        en: [
            "mode.chat":   .text("Chat"),
            "mode.search": .text("Search"),
            "mode.images": .text("Images"),
        ]
    )
}
