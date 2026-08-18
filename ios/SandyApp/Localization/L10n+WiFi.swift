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
            "trying":      .text("عم تجرّب… %d ثانية"),
            "safety":      .text("لو كلمة السر غلط، بترجع للشبكة القديمة لحالها خلال نص دقيقة. ما في خطر."),
            "sendFailed":  .text("ما قدرت أبعت الطلب. تأكّد إنك متصل وجرّب كمان مرّة."),
            "rolledBack":  .text("ما قدرت توصل للشبكة الجديدة ورجعت للقديمة. تأكّد من الاسم وكلمة السر."),
        ],
        en: [
            "title":       .text("Wi-Fi network"),
            "current":     .text("Current network"),
            "unknown":     .text("Unknown"),
            "new":         .text("New network"),
            "ssid":        .text("Network name"),
            "password":    .text("Password"),
            "send":        .text("Move it over"),
            "trying":      .text("Trying… %d s"),
            "safety":      .text("If the password is wrong it returns to the old network by itself within half a minute. Nothing to lose."),
            "sendFailed":  .text("Couldn't send the request. Check your connection and try again."),
            "rolledBack":  .text("It couldn't reach the new network and went back to the old one. Check the name and password."),
        ]
    )
}
