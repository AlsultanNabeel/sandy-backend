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
            "photos":      .text("الألبوم"),
            "callIdle":      .text("سكّرت المكالمة لأنه ما حدا حكى من فترة."),
            "callTimeLimit": .text("المكالمة وصلت أقصى مدة إلها. افتح وحدة جديدة لو بدك نكمّل."),
            "callMinutesExceeded": .text("خلصت دقايق الحكي لليوم. بترجع بكرا، أو رقّي اشتراكك."),
        ],
        en: [
            "mode.chat":   .text("Chat"),
            "mode.search": .text("Search"),
            "mode.images": .text("Images"),
            "photos":      .text("Album"),
            "callIdle":      .text("The call ended because nobody spoke for a while."),
            "callTimeLimit": .text("The call reached its maximum length. Start a new one to carry on."),
            "callMinutesExceeded": .text("You've used today's talk minutes. They come back tomorrow, or upgrade your plan."),
        ]
    )
}
