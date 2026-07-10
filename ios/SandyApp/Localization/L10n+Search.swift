import Foundation

// Namespace: search — the Search tab. External web research (Exa) + place search
// (Google Places) over GET /api/research, shown as structured results.
enum L10nSearch {
    static let ns = "search"

    static let table = L10nTable(
        ar: [
            "placeholder":  .text("دوّر عن أي إشي…"),
            "kind.web":     .text("الويب"),
            "kind.places":  .text("أماكن"),
            "hint":         .text("اكتب واطلب — بدوّرلك على الويب وعالأماكن وأجيبلك النتائج."),
            "empty":        .text("ما لقيت نتائج — جرّب كلمات ثانية."),
            "error":        .text("معلش، ما قدرت أكمّل البحث — جرّب كمان مرة."),
            "places.map":   .text("الخريطة"),
            "places.call":  .text("اتصال"),
            "places.site":  .text("الموقع"),
        ],
        en: [
            "placeholder":  .text("Search anything…"),
            "kind.web":     .text("Web"),
            "kind.places":  .text("Places"),
            "hint":         .text("Type and search — I'll look across the web and places and bring back results."),
            "empty":        .text("No results — try different words."),
            "error":        .text("Sorry, I couldn't finish the search — try again."),
            "places.map":   .text("Map"),
            "places.call":  .text("Call"),
            "places.site":  .text("Website"),
        ]
    )
}
