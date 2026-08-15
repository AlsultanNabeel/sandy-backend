import Foundation

// Namespace: futureMessages — a message to your future self. Schedule a note now
// (text + a future date/time); Sandy keeps it and brings it back to you when the
// day comes. Create / list / delete over /api/future-messages.
enum L10nFutureMessages {
    static let ns = "futureMessages"

    static let table = L10nTable(
        ar: [
            "intro":            .text("اكتب كلمة لنفسك بالمستقبل — وأنا بحفظها وبرجّعها إلك يوم موعدها 💌"),
            "empty":            .text("لا توجد رسائل مجدولة بعد — اكتب أول رسالة لنفسك في المستقبل."),
            "add":              .text("رسالة جديدة"),
            "addTitle":         .text("رسالة لنفسك المستقبلي"),
            "delete":           .text("احذف"),
            "sheet.textPrompt": .text("شو الكلمة اللي تبي توصلك؟"),
            "sheet.placeholder": .text("اكتب رسالتك لنفسك…"),
            "sheet.timePrompt": .text("امتى تبي توصلك؟"),
            "save":             .text("احفظها لي"),
            "deliverPrefix":    .text("بتوصلك"),
            "pastGuard":        .text("اختار وقت بالمستقبل — هاي رسالة لبكرة مش لليوم 🙂"),
            "errorLoad":        .text("تعذّر تحميل رسائلك المجدولة. أعد المحاولة."),
            "errorAdd":         .text("تعذّر حفظ الرسالة. أعد المحاولة."),
            "errorDelete":      .text("تعذّر حذف الرسالة. أعد المحاولة."),
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
            "errorLoad":        .text("Couldn't load your scheduled messages. Try again."),
            "errorAdd":         .text("Couldn't save the message. Try again."),
            "errorDelete":      .text("Couldn't delete the message. Try again."),
        ]
    )
}
