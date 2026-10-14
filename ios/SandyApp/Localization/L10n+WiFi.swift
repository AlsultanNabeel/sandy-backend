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
            "current":     .text("الشبكة الحالية"),
            "unknown":     .text("غير معروفة"),
            "new":         .text("شبكة جديدة"),
            "ssid":        .text("اسم الشبكة"),
            "password":    .text("كلمة السر"),
            "send":        .text("انقلها للشبكة"),
            "trying":      .text("عم تجرّب… %@ ثانية"),
            "safety":      .text("لو كلمة السر غلط أو الشبكة بلا إنترنت، بترجع للشبكة القديمة لحالها خلال أقل من دقيقة. ما في خطر."),
            "sendFailed":  .text("ما قدرت أبعت الطلب."),
            "err.offline":  .text("ما وصلت للخادم. هاي مشكلة نت جهازك، مش الروبوت."),
            "err.session":  .text("انتهت جلستك. سجّل دخولك وجرّب كمان مرّة."),
            "err.notYours": .text("هالوحدة مش مربوطة بحسابك."),
            "err.notSent":  .text("الخادم ما قدر يوصل الرسالة للوسيط. الروبوت غالبًا مطفي أو مقطوع."),
            "err.noNode":   .text("ما في وحدة محدّدة."),
            "err.tooLong":  .text("الاسم أطول من اثنين وثلاثين حرف أو كلمة السر أطول من أربعة وستين."),
            "err.badPassword": .text("كلمة السر لازم تكون من ثمانية لثلاثة وستين حرف، أو فاضية لو الشبكة مفتوحة."),
            "err.badChars": .text("في سطر جديد جوّا الاسم أو كلمة السر — شيله."),
            "rolledBack":  .text("ما قدرت توصل للشبكة الجديدة أو للإنترنت منها، ورجعت للقديمة. تأكّد من الاسم وكلمة السر وإنه في إنترنت."),
        ],
        en: [
            "title":       .text("Wi-Fi network"),
            "current":     .text("Current network"),
            "unknown":     .text("Unknown"),
            "new":         .text("New network"),
            "ssid":        .text("Network name"),
            "password":    .text("Password"),
            "send":        .text("Move it over"),
            "trying":      .text("Trying… %@ s"),
            "safety":      .text("If the password is wrong or the network has no internet, it returns to the old network by itself within a minute. Nothing to lose."),
            "sendFailed":  .text("Couldn't send the request."),
            "err.offline":  .text("Couldn't reach the server. That's your phone's connection, not the robot."),
            "err.session":  .text("Your session expired. Sign in and try again."),
            "err.notYours": .text("This node isn't paired to your account."),
            "err.notSent":  .text("The server couldn't reach the broker. The robot is probably off or disconnected."),
            "err.noNode":   .text("No node selected."),
            "err.tooLong":  .text("The name is over 32 characters or the password over 64."),
            "err.badPassword": .text("The password must be 8 to 63 characters, or empty for an open network."),
            "err.badChars": .text("There's a newline in the name or password — remove it."),
            "rolledBack":  .text("It couldn't reach the new network or the internet through it, and went back to the old one. Check the name, the password and the internet."),
        ]
    )
}
