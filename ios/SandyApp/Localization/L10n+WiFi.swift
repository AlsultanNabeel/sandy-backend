import Foundation

// Namespace: wifi — moving a board onto another network from the app.
//
// The wording carries the safety guarantee, because it is what makes the
// feature usable: someone who knows the board comes back on its own will try,
// and someone who does not will be scared of a button that is already safe.
enum L10nWiFi {
    static let ns = "wifi"

    static let table = L10nTable(
        ar: [
            "title":       .text("شبكة الواي فاي"),
            "board.brain":  .text("الدماغ"),
            "board.camera": .text("الكاميرا"),
            "current":     .text("الشبكة الحالية"),
            "unknown":     .text("غير معروفة"),
            "new":         .text("شبكة جديدة"),
            "ssid":        .text("اسم الشبكة"),
            "password":    .text("كلمة السر"),
            "send":        .text("انقلها للشبكة"),
            "trying":      .text("عم تجرّب… %d ثانية"),
            "safety":      .text("لو كلمة السر غلط، بترجع للشبكة القديمة لحالها خلال نص دقيقة. ما في خطر."),
            "sendFailed":  .text("ما قدرت أبعت الطلب."),
            "err.offline":  .text("ما وصلت للخادم. هاي مشكلة نت جهازك، مش الروبوت."),
            "err.session":  .text("انتهت جلستك. سجّل دخولك وجرّب كمان مرّة."),
            "err.notYours": .text("هالوحدة مش مربوطة بحسابك."),
            "err.notSent":  .text("الخادم ما قدر يوصل الرسالة للوسيط. الروبوت غالبًا مطفي أو مقطوع."),
            "err.noNode":   .text("ما في وحدة محدّدة."),
            "err.badBoard": .text("لوح غير معروف."),
            "err.tooLong":  .text("الاسم أطول من اثنين وثلاثين حرف أو كلمة السر أطول من أربعة وستين."),
            "err.badChars": .text("في سطر جديد جوّا الاسم أو كلمة السر — شيله."),
            "rolledBack":  .text("ما قدرت توصل للشبكة الجديدة ورجعت للقديمة. تأكّد من الاسم وكلمة السر."),
        ],
        en: [
            "title":       .text("Wi-Fi network"),
            "board.brain":  .text("Brain"),
            "board.camera": .text("Camera"),
            "current":     .text("Current network"),
            "unknown":     .text("Unknown"),
            "new":         .text("New network"),
            "ssid":        .text("Network name"),
            "password":    .text("Password"),
            "send":        .text("Move it over"),
            "trying":      .text("Trying… %d s"),
            "safety":      .text("If the password is wrong it returns to the old network by itself within half a minute. Nothing to lose."),
            "sendFailed":  .text("Couldn't send the request."),
            "err.offline":  .text("Couldn't reach the server. That's your phone's connection, not the robot."),
            "err.session":  .text("Your session expired. Sign in and try again."),
            "err.notYours": .text("This node isn't paired to your account."),
            "err.notSent":  .text("The server couldn't reach the broker. The robot is probably off or disconnected."),
            "err.noNode":   .text("No node selected."),
            "err.badBoard": .text("Unknown board."),
            "err.tooLong":  .text("The name is over 32 characters or the password over 64."),
            "err.badChars": .text("There's a newline in the name or password — remove it."),
            "rolledBack":  .text("It couldn't reach the new network and went back to the old one. Check the name and password."),
        ]
    )
}
