import Foundation

// Namespace: tips — the one-time tips (Services/Guidance.swift) and Today's controls.
enum L10nTips {
    static let ns = "tips"

    static let table = L10nTable(
        ar: [
            "gotIt": .text("فهمت"),
            "orbTitle": .text("اضغط مطوّل لتتصل"),
            "orbBody": .text("ضغطة عادية بتفتح الشات، وضغطة طويلة على ساندي بتتصل فيها بالصوت."),
            "rowsTitle": .text("في خيارات أكتر"),
            "rowsBody": .text("اكبس على أي إشي لتعدّله، واضغط مطوّل للتأجيل أو التعليم أو الحذف."),
            "dayTitle": .text("شوف يوم بعينه"),
            "dayBody": .text("اكبس على أي مربع بشريط الشهر وبتشوف شو صار بهاليوم بس."),
            "messageTitle": .text("الرسائل إلها خيارات"),
            "messageBody": .text("اضغط مطوّل على أي رسالة: نسخ، مشاركة، تكتبها ساندي من جديد، أو تعدّل رسالتك."),
            "home": .text("التحكم بالبيت"),
            "robot": .text("روبوت ساندي"),
            "orAsk": .text("أو قولي لساندي شو بدك"),
        ],
        en: [
            "gotIt": .text("Got it"),
            "orbTitle": .text("Hold to call"),
            "orbBody": .text("A tap opens the chat; holding Sandy calls her by voice."),
            "rowsTitle": .text("There's more here"),
            "rowsBody": .text("Tap anything to edit it; hold it to snooze, mark done or delete."),
            "dayTitle": .text("See a single day"),
            "dayBody": .text("Tap any square on the month strip to see just that day."),
            "messageTitle": .text("Messages have options"),
            "messageBody": .text("Hold any message to copy, share, have Sandy write it again, or edit yours."),
            "home": .text("Home control"),
            "robot": .text("Sandy robot"),
            "orAsk": .text("or just tell Sandy what you want"),
        ]
    )
}
