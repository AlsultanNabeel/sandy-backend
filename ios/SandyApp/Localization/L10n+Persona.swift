import Foundation

// Namespace: persona — per-user personality customization (dialect + custom
// instructions). Tucked in the Profile archive: an advanced/opt-in place. Her
// Palestinian identity is NOT editable here — it's locked server-side.
enum L10nPersona {
    static let ns = "persona"

    static let table = L10nTable(
        ar: [
            "title":              .text("شخصية ساندي"),
            "intro":              .text("لو ما غيّرت شي هون، بتضل ساندي بشخصيتها اللطيفة الافتراضية. هويتها الفلسطينية ثابتة دايماً ومش قابلة للتغيير."),
            "dialectLabel":       .text("اللهجة"),
            "customLabel":        .text("تعليمات مخصّصة (اختياري)"),
            "customPlaceholder":  .text("مثلاً: كوني مرحة أكتر، أو رسمية بالردود، أو اختصري دايماً..."),
            "customHint":         .text("لو تركتها فاضية، بتستخدم ساندي شخصيتها الافتراضية اللطيفة."),
            "save":               .text("حفظ"),
            "reset":              .text("رجوع للشخصية الافتراضية"),
            "saved":              .text("تم الحفظ ✅"),
            "saveError":          .text("تعذّر الحفظ. أعد المحاولة."),
            "loadError":          .text("تعذّر تحميل إعدادات الشخصية."),
        ],
        en: [
            "title":              .text("Sandy's Personality"),
            "intro":              .text("If you leave this untouched, Sandy keeps her default warm personality. Her Palestinian identity is always fixed and can't be changed."),
            "dialectLabel":       .text("Dialect"),
            "customLabel":        .text("Custom instructions (optional)"),
            "customPlaceholder":  .text("e.g. be more playful, more formal, always keep it short..."),
            "customHint":         .text("Leave this empty to keep Sandy's default friendly personality."),
            "save":               .text("Save"),
            "reset":              .text("Reset to default personality"),
            "saved":              .text("Saved ✅"),
            "saveError":          .text("Couldn't save. Try again."),
            "loadError":          .text("Couldn't load personality settings."),
        ]
    )
}
