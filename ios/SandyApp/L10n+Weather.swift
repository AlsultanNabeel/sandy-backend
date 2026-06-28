import Foundation

// Namespace: weather — the Weather screen + the embeddable Home card. Live
// current conditions for a city over GET /api/weather. Sandy's warm voice;
// male user → masculine forms.
enum L10nWeather {
    static let ns = "weather"

    static let table = L10nTable(
        ar: [
            "title":          .text("الطقس"),
            "intro":          .text("شوف حالة الجو بمدينتك — غيّر المدينة وقت ما بدك."),
            "cityField":      .text("المدينة"),
            "cityPlaceholder": .text("اكتب اسم مدينتك…"),
            "change":         .text("غيّر المدينة"),
            "save":           .text("احفظ"),
            "feelsLike":      .text("الشعور الفعلي"),
            "humidity":       .text("الرطوبة"),
            "high":           .text("العظمى"),
            "low":            .text("الصغرى"),
            "sunset":         .text("الغروب"),
            "empty":          .text("اكتب اسم مدينة وبجيبلك حالة الجو فيها."),
            "errorLoad":      .text("معلش، ما قدرت أجيب الطقس هلأ — جرّب كمان مرة."),
            "retry":          .text("جرّب كمان مرة"),
        ],
        en: [
            "title":          .text("Weather"),
            "intro":          .text("Check the weather in your city — change the city whenever you like."),
            "cityField":      .text("City"),
            "cityPlaceholder": .text("Type your city…"),
            "change":         .text("Change city"),
            "save":           .text("Save"),
            "feelsLike":      .text("Feels like"),
            "humidity":       .text("Humidity"),
            "high":           .text("High"),
            "low":            .text("Low"),
            "sunset":         .text("Sunset"),
            "empty":          .text("Type a city and I'll bring you its weather."),
            "errorLoad":      .text("Sorry, I couldn't get the weather right now — try again."),
            "retry":          .text("Try again"),
        ]
    )
}
