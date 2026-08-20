import Foundation

// Namespace: account — ربط الروبوت، بيعه، وحذف الحساب.
//
// نصوص هالشاشة أهم من غيرها لأنها بتوصف أفعال ما إلها رجعة. الجُمَل بتقول شو
// **بيصير**، مش شو بينضغط: «بينمسح من اللوح» بدل «إعادة ضبط»، و«بيروح ولا
// بيرجع» بدل «تأكيد».
enum L10nAccount {
    static let ns = "account"

    static let table = L10nTable(
        ar: [
            "title":            .text("الحساب والروبوت"),

            "pair":             .text("اربط روبوت"),
            "pair.hint":        .text("الكود مطبوع تحت الروبوت. أول حساب بيربطه بيملكه."),
            "pair.code":        .text("كود الروبوت"),
            "pair.button":      .text("اربط"),
            "pair.taken":       .text("هاد الروبوت مربوط بحساب تاني. لازم صاحبه يفكّه أول."),
            "pair.tooMany":     .text("محاولات كتير. استنّى شوي وجرّب كمان مرّة."),
            "pair.failed":      .text("ما قدرت أربطه. تأكّد من الكود."),

            "robots":           .text("روبوتاتك"),

            "sell":             .text("فكّ الربط"),
            "sell.confirm":     .text("تفكّ ربط هالروبوت؟"),
            "sell.warn":        .text("بينمسح من اللوح اسم شبكتك وكلمة سرّها، وبيصير حدا تاني يقدر يربطه. للبيع أو الإهداء."),
            "sell.done":        .text("انفكّ وانمسح. جاهز لصاحبه الجديد."),
            "sell.offline":     .text("انفكّ من حسابك، بس اللوح كان مطفي فما انمسح. شغّله وفكّه وهو متصل قبل ما تبيعه."),
            "sell.failed":      .text("ما قدرت أفكّه. جرّب كمان مرّة."),

            "reset":            .text("صفّر كل البيانات"),
            "reset.confirm":    .text("تمسح كل بياناتك؟"),
            "reset.warn":       .text("بيمسح المحادثات والذاكرة والمهام واليوميات والصور وبصمة صوتك — وبيخلّي حسابك وروبوتك زي ما هنّ. للبداية من جديد."),
            "reset.done":       .text("انمسح كل إشي. صفحة بيضا."),
            "reset.failed":     .text("ما قدرت أمسح. جرّب كمان مرّة."),

            "danger":           .text("حذف الحساب"),
            "delete":           .text("احذف حسابي"),
            "delete.confirm":   .text("تحذف حسابك نهائيًا؟"),
            "delete.warn":      .text("بيروح كل إشي: بصمة صوتك، يومياتك، صورك، مصاريفك، وكل محادثة حكيتها معها. ما في رجعة."),
            "delete.failed":    .text("ما قدرت أحذف الحساب. جرّب كمان مرّة."),
        ],
        en: [
            "title":            .text("Account & robot"),

            "pair":             .text("Pair a robot"),
            "pair.hint":        .text("The code is printed underneath. The first account to pair it owns it."),
            "pair.code":        .text("Robot code"),
            "pair.button":      .text("Pair"),
            "pair.taken":       .text("This robot belongs to another account. Its owner has to release it first."),
            "pair.tooMany":     .text("Too many attempts. Wait a moment and try again."),
            "pair.failed":      .text("Couldn't pair it. Check the code."),

            "robots":           .text("Your robots"),

            "sell":             .text("Release"),
            "sell.confirm":     .text("Release this robot?"),
            "sell.warn":        .text("Your network name and password are erased from the board, and someone else can pair it. For selling or giving away."),
            "sell.done":        .text("Released and wiped. Ready for its next owner."),
            "sell.offline":     .text("Released from your account, but the board was off so nothing was erased. Power it on and release it while connected before selling."),
            "sell.failed":      .text("Couldn't release it. Try again."),

            "reset":            .text("Erase all data"),
            "reset.confirm":    .text("Erase all your data?"),
            "reset.warn":       .text("Clears conversations, memory, tasks, journal, photos and your voiceprint — and leaves your account and robot as they are. For starting over."),
            "reset.done":       .text("Everything cleared. Clean slate."),
            "reset.failed":     .text("Couldn't erase it. Try again."),

            "danger":           .text("Delete account"),
            "delete":           .text("Delete my account"),
            "delete.confirm":   .text("Delete your account permanently?"),
            "delete.warn":      .text("Everything goes: your voiceprint, journal, photos, expenses, and every conversation you've had with her. This cannot be undone."),
            "delete.failed":    .text("Couldn't delete the account. Try again."),
        ]
    )
}
