import Foundation

// Namespace: robot — the Robot tab (room-node device control over MQTT). Lists
// scenes, applies them (publishes room/cmd/* to the room-node), and adds/edits/
// deletes them. owner-gated on the backend. Moved out of the focus.scenes.* keys
// when scenes became their own tab.
enum L10nRobot {
    static let ns = "robot"

    static let table = L10nTable(
        ar: [
            "apply":          .text("شغّل"),
            "applied":        .text("تمام — أرسلتها للغرفة 🏠"),
            "appliedOffline": .text("حفظت المشهد، بس الغرفة مش متّصلة."),
            "applyError":     .text("معلش، ما قدرت أطبّق المشهد."),
            "add":            .text("مشهد جديد"),
            "delete":         .text("حذف"),
            "edit":           .text("تعديل"),
            "save":           .text("حفظ"),
            "cancel":         .text("إلغاء"),
            "addAction":      .text("إضافة جهاز"),
            "namePlaceholder":  .text("اسم مختصر (إنجليزي)"),
            "labelPlaceholder": .text("الاسم الظاهر"),
            "empty":          .text("ما في مشاهد بعد — أضف وحدة."),
            "nameExists":     .text("في مشهد بنفس الاسم."),
            "builtinDel":     .text("هاد مشهد جاهز ما بينحذف."),
            "saveError":      .text("معلش، ما قدرت أحفظ المشهد."),
            "loadError":      .text("معلش، ما قدرت أجيب المشاهد — اسحب للتحديث."),

            // ── فحص الجسم (RobotTestView) ──
            // شاشة الفحص من بطاقة الوحدة بصفحة التحكّم. النص بيشرح **الطريقة**
            // (اكتم واحد، احكي، راقب التاني) مش بيسمّي الأزرار — الأزرار بتسمّي
            // حالها. هاد السؤال الوحيد اللي باقي التطبيق ما بيجاوبه.
            "test.title":            .text("فحص الجسم"),
            "test.mics":             .text("المايكات"),
            "test.mics.hint":        .text("اكتم واحد، احكي، وشوف التاني لحاله بيتحرّك. لو التنين ما تحرّكوا، هي ما بتسمع. لو تحرّك المكتوم، المايكات معكوسة بالتوصيل."),
            "test.mics.noreadings":  .text("ما وصلتني قراءات من المايكات. غالبًا نسخة الفيرموير ع اللوح أقدم من هاي الميزة — احرقها من جديد."),
            "test.mic.left":         .text("المايك الشمال"),
            "test.mic.right":        .text("المايك اليمين"),
            "test.speaker":          .text("السماعة"),
            "test.speaker.hint":     .text("شغّل نغمة الفحص. بتمشي بنفس طريق صوتها الحقيقي، فلو سمعتها معناها المسار كله سليم."),
            "test.body":             .text("الوش والرقبة"),
            "test.offline":          .text("الروبوت مش متّصل هلّق. رح تشوف آخر قراءة وصلتني، بس الأوامر ما رح توصله."),
        ],
        en: [
            "apply":          .text("Run"),
            "applied":        .text("Done — sent to the room 🏠"),
            "appliedOffline": .text("Saved the scene, but the room is offline."),
            "applyError":     .text("Sorry, I couldn't apply the scene."),
            "add":            .text("New scene"),
            "delete":         .text("Delete"),
            "edit":           .text("Edit"),
            "save":           .text("Save"),
            "cancel":         .text("Cancel"),
            "addAction":      .text("Add device"),
            "namePlaceholder":  .text("Short name (English)"),
            "labelPlaceholder": .text("Display name"),
            "empty":          .text("No scenes yet — add one."),
            "nameExists":     .text("A scene with that name exists."),
            "builtinDel":     .text("This is a built-in scene; it can't be deleted."),
            "saveError":      .text("Sorry, I couldn't save the scene."),
            "loadError":      .text("Sorry, I couldn't load scenes — pull to refresh."),

            // ── Body test (RobotTestView) ──
            // Reached from the node card on the Control page.
            "test.title":            .text("Body test"),
            "test.mics":             .text("Microphones"),
            "test.mics.hint":        .text("Mute one, speak, and watch the other move on its own. If neither moves, she isn't hearing you. If the muted one moves, they're wired the wrong way round."),
            "test.mics.noreadings":  .text("No microphone readings have arrived. The board is probably running firmware older than this feature — reflash it."),
            "test.mic.left":         .text("Left microphone"),
            "test.mic.right":        .text("Right microphone"),
            "test.speaker":          .text("Speaker"),
            "test.speaker.hint":     .text("Play the test tone. It travels the same path as her real voice, so hearing it means the whole output path works."),
            "test.body":             .text("Face and neck"),
            "test.offline":          .text("The robot is offline right now. You'll see the last readings I got, but commands won't reach it."),
        ]
    )
}
