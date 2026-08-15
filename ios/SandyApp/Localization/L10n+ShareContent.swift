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
            "empty.hint":   .text("لم أتعرّف على اهتماماتك بعد — أخبرني بما تحبّه."),
            "empty.results": .text("لا توجد نتائج حاليًا. جرّب لاحقًا."),
            "empty.saved":  .text("ما حفظت إشي بعد — أي بطاقة بتعجبك احفظها وبتلاقيها هون."),
            "error":        .text("تعذّر تحميل المحتوى. أعد المحاولة."),
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
            "empty.hint":   .text("I don't know your interests yet — tell me what you like."),
            "empty.results": .text("No results right now. Try later."),
            "empty.saved":  .text("Nothing saved yet — save any card you like and find it here."),
            "error":        .text("Couldn't load content. Try again."),
        ]
    )
}
