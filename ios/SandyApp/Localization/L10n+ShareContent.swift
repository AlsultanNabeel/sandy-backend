import Foundation

// Namespace: shareContent — the "Share interesting content" tool screen. Sandy
// surfaces content from your own top interests over GET /api/share/suggest, and
// lets you keep a card (GET/POST/DELETE /api/share/saved).
enum L10nShareContent {
    static let ns = "shareContent"

    static let table = L10nTable(
        ar: [
            "intro":        .text("بناءً على اللي بتحكيلي عنه، جمعتلك شوية محتوى حلو يهمّك."),
            "topic":        .text("عن"),
            "seg.suggested": .text("مقترح إلك"),
            "seg.saved":    .text("المحفوظ"),
            "save":         .text("احفظها"),
            "saved":        .text("اتحفظت 💛"),
            "remove":       .text("شيلها"),
            "open":         .text("افتح"),
            "refresh":      .text("جدّدلي"),
            "empty.hint":   .text("لسا ما عرفت اهتماماتك — احكيلي عن إشي بتحبّه وبجيبلك محتوى عنه."),
            "empty.results": .text("ما لقيت إشي هلق — جرّبني كمان شوي."),
            "empty.saved":  .text("ما حفظت إشي بعد — أي بطاقة بتعجبك احفظها وبتلاقيها هون."),
            "error":        .text("معلش، ما قدرت أجيب المحتوى — جرّب كمان مرة."),
        ],
        en: [
            "intro":        .text("From what you tell me about, I gathered some good reads for you."),
            "topic":        .text("About"),
            "seg.suggested": .text("For you"),
            "seg.saved":    .text("Saved"),
            "save":         .text("Save"),
            "saved":        .text("Saved 💛"),
            "remove":       .text("Remove"),
            "open":         .text("Open"),
            "refresh":      .text("Refresh"),
            "empty.hint":   .text("I don't know your interests yet — tell me about something you like and I'll bring content on it."),
            "empty.results": .text("Nothing right now — try me again in a bit."),
            "empty.saved":  .text("Nothing saved yet — save any card you like and find it here."),
            "error":        .text("Sorry, I couldn't fetch the content — try again."),
        ]
    )
}
