import Foundation

// Namespace: gifts — the Digital Gifts screen (حياتي hub). Little warm things
// Sandy writes for someone (poem/quote/pep/smile/joke/riddle), kept for a
// recipient + occasion, optionally scheduled. Backed by /api/gifts. No Telegram.
enum L10nGifts {
    static let ns = "gifts"

    static let table = L10nTable(
        ar: [
            "intro":        .text("هاي الهدايا الصغيرة اللي ساندي جهّزتها — لإلك أو لحدا بتحبّه، تقدر تضيف أو تحذف أي وحدة."),
            "empty":        .text("لسّا ما في هدايا — خلّيني أكتبلك إشي صغير يفرّح حدا بتحبّه."),
            "errorLoad":    .text("معلش، ما قدرت أجيب الهدايا — اسحب للتحديث."),
            "errorAdd":     .text("معلش، ما قدرت أحفظ الهدية — جرّب كمان مرة."),
            "errorDelete":  .text("معلش، ما قدرت أحذف الهدية — جرّب كمان مرة."),
            "errorGenerate": .text("معلش، ما قدرت أكتبها هلّأ — جرّب كمان مرة."),

            // إجراءات الصف + الزر
            "add":          .text("هدية جديدة"),
            "delete":       .text("حذف"),

            // الورقة (إضافة)
            "addTitle":     .text("هدية جديدة"),
            "save":         .text("احفظها"),
            "kindSection":  .text("نوع الهدية"),
            "recipientSection": .text("لمين؟"),
            "recipientPlaceholder": .text("مثلاً: لأمي، لصديقي خالد…"),
            "occasionSection": .text("المناسبة"),
            "occasionPlaceholder": .text("مثلاً: عيد ميلاد، تخرّج، مجرّد محبة…"),
            "scheduleSection": .text("موعد (اختياري)"),
            "scheduleToggle": .text("جدوِل ليوم معيّن"),
            "contentSection": .text("نص الهدية"),
            "contentPlaceholder": .text("اكتبها بنفسك، أو خلّي ساندي تكتبها إلك."),
            "generate":     .text("خلّي ساندي تكتبها"),

            // عناوين الأنواع
            "kind.poem":    .text("شعر"),
            "kind.quote":   .text("اقتباس"),
            "kind.motivation": .text("تحفيز"),
            "kind.smile":   .text("ابتسامة"),
            "kind.joke":    .text("نكتة"),
            "kind.riddle":  .text("لغز"),

            // عرض الصف
            "scheduledFor": .text("مجدولة لـ %@"),
            "saved":        .text("محفوظة"),
        ],
        en: [
            "intro":        .text("Little gifts Sandy put together — for you or someone you love. Add or delete any."),
            "empty":        .text("No gifts yet — let me write something small to make someone you love smile."),
            "errorLoad":    .text("Sorry, I couldn't load your gifts — pull to refresh."),
            "errorAdd":     .text("Sorry, I couldn't save that gift — give it another try."),
            "errorDelete":  .text("Sorry, I couldn't delete that gift — give it another try."),
            "errorGenerate": .text("Sorry, I couldn't write it just now — give it another try."),

            // row actions + button
            "add":          .text("New gift"),
            "delete":       .text("Delete"),

            // add sheet
            "addTitle":     .text("New gift"),
            "save":         .text("Save it"),
            "kindSection":  .text("Gift type"),
            "recipientSection": .text("For whom?"),
            "recipientPlaceholder": .text("e.g. for Mom, for my friend Khaled…"),
            "occasionSection": .text("Occasion"),
            "occasionPlaceholder": .text("e.g. birthday, graduation, just love…"),
            "scheduleSection": .text("Date (optional)"),
            "scheduleToggle": .text("Schedule for a day"),
            "contentSection": .text("Gift text"),
            "contentPlaceholder": .text("Write it yourself, or let Sandy write it for you."),
            "generate":     .text("Let Sandy write it"),

            // kind titles
            "kind.poem":    .text("Poem"),
            "kind.quote":   .text("Quote"),
            "kind.motivation": .text("Pep"),
            "kind.smile":   .text("Smile"),
            "kind.joke":    .text("Joke"),
            "kind.riddle":  .text("Riddle"),

            // row display
            "scheduledFor": .text("Scheduled for %@"),
            "saved":        .text("Saved"),
        ]
    )
}
