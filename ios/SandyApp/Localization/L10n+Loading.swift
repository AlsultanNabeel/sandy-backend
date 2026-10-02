import Foundation

// Namespace: loading — what Sandy says while you wait (DesignSystem/Loading.swift).
// Each line takes the user's name for %@.
enum L10nLoading {
    static let ns = "loading"

    static let table = L10nTable(
        ar: [
            "label": .text("عم يحمّل"),
            "lines": .items([
                "لحظة يا %@، عم فكّر 🤔",
                "ثواني يا %@ وبكون جاهزة ✨",
                "عم رتّبلك الأمور يا %@ 🌸",
                "استنّاني شوي يا %@، قرّبت 😌",
                "عم دوّر يا %@، ما تروح بعيد 🤍",
                "يا %@، شغّالة عليها هلأ 💪",
                "شوي صبر يا %@، الحلو ما بيستعجل 😄",
                "عم جمّع أفكاري يا %@ 🧠",
                "تقريباً خلصت يا %@ 🙌",
                "خليني أشوف يا %@… 👀",
            ]),
            "drawLines": .items([
                "عم ارسملك يا %@ 🎨",
                "يا %@، عم ختار الألوان 🖌️",
                "لحظة يا %@، الرسمة عم تطلع ✨",
                "عم زبّط التفاصيل يا %@ 🔍",
                "يا %@، بدّي إياها تطلع حلوة 🌈",
                "قرّبت خلّص الرسمة يا %@ 🖼️",
                "شوي صبر يا %@، الفن بدو وقت 😌",
                "عم حط اللمسات الأخيرة يا %@ 💫",
            ]),
        ],
        en: [
            "label": .text("Loading"),
            "lines": .items([
                "One moment %@, thinking 🤔",
                "A few seconds %@ and I'm ready ✨",
                "Sorting things out for you %@ 🌸",
                "Bear with me %@, almost there 😌",
                "Looking it up %@, don't go far 🤍",
                "On it right now %@ 💪",
                "Patience %@, good things take a moment 😄",
                "Gathering my thoughts %@ 🧠",
                "Nearly done %@ 🙌",
                "Let me see %@… 👀",
            ]),
            "drawLines": .items([
                "Drawing it for you %@ 🎨",
                "Picking the colours %@ 🖌️",
                "One moment %@, the picture is coming ✨",
                "Getting the details right %@ 🔍",
                "I want it to look lovely %@ 🌈",
                "Almost done with the drawing %@ 🖼️",
                "Patience %@, art takes a moment 😌",
                "Final touches %@ 💫",
            ]),
        ]
    )
}
