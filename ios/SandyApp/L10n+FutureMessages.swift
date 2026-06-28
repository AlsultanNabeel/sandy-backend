import Foundation

// Namespace: futureMessages — a message to your future self. Schedule a note now
// (text + a future date/time); Sandy keeps it and brings it back to you when the
// day comes. Create / list / delete over /api/future-messages.
enum L10nFutureMessages {
    static let ns = "futureMessages"

    static let table = L10nTable(
        ar: [
            "intro":            .text("اكتب كلمة لنفسك بالمستقبل — وأنا بحفظها وبرجّعها إلك يوم موعدها 💌"),
            "empty":            .text("ما في رسائل مجدولة بعد — اكتب أول كلمة لنفسك المستقبلي."),
            "add":              .text("رسالة جديدة"),
            "addTitle":         .text("رسالة لنفسك المستقبلي"),
            "delete":           .text("احذف"),
            "sheet.textPrompt": .text("شو الكلمة اللي تبي توصلك؟"),
            "sheet.placeholder": .text("اكتب رسالتك لنفسك…"),
            "sheet.timePrompt": .text("امتى تبي توصلك؟"),
            "save":             .text("احفظها لي"),
            "deliverPrefix":    .text("بتوصلك"),
            "pastGuard":        .text("اختار وقت بالمستقبل — هاي رسالة لبكرة مش لليوم 🙂"),
            "errorLoad":        .text("معلش، ما قدرت أجيب رسائلك المجدولة — جرّب كمان مرة."),
            "errorAdd":         .text("معلش، ما قدرت أحفظ الرسالة — جرّب كمان مرة."),
            "errorDelete":      .text("معلش، ما قدرت أحذف الرسالة — جرّب كمان مرة."),
        ],
        en: [
            "intro":            .text("Write a note to your future self — I'll keep it and bring it back to you on the day 💌"),
            "empty":            .text("No scheduled messages yet — write your first note to future you."),
            "add":              .text("New message"),
            "addTitle":         .text("A message to future you"),
            "delete":           .text("Delete"),
            "sheet.textPrompt": .text("What do you want to reach you?"),
            "sheet.placeholder": .text("Write your note to yourself…"),
            "sheet.timePrompt": .text("When should it reach you?"),
            "save":             .text("Keep it for me"),
            "deliverPrefix":    .text("Arrives"),
            "pastGuard":        .text("Pick a time in the future — this is a note for later, not today 🙂"),
            "errorLoad":        .text("Sorry, I couldn't load your scheduled messages — try again."),
            "errorAdd":         .text("Sorry, I couldn't save the message — try again."),
            "errorDelete":      .text("Sorry, I couldn't delete the message — try again."),
        ]
    )
}
