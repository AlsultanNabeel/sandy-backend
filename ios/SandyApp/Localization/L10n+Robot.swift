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
            "applyError":     .text("تعذّر تطبيق المشهد."),
            "add":            .text("مشهد جديد"),
            "delete":         .text("حذف"),
            "edit":           .text("تعديل"),
            "save":           .text("حفظ"),
            "cancel":         .text("إلغاء"),
            "addAction":      .text("إضافة جهاز"),
            "namePlaceholder":  .text("اسم مختصر (إنجليزي)"),
            "labelPlaceholder": .text("الاسم الظاهر"),
            "empty":          .text("لا توجد مشاهد بعد — أضف مشهدًا."),
            "nameExists":     .text("في مشهد بنفس الاسم."),
            "builtinDel":     .text("هاد مشهد جاهز ما بينحذف."),
            "saveError":      .text("تعذّر حفظ المشهد."),
            "loadError":      .text("تعذّر تحميل المشاهد. اسحب للتحديث."),

            // ── فحص الجسم (RobotTestView) ──
            // شاشة الفحص من بطاقة الوحدة بصفحة التحكّم. النص بيشرح **الطريقة**
            // (اكتم واحد، احكي، راقب التاني) مش بيسمّي الأزرار — الأزرار بتسمّي
            // حالها. هاد السؤال الوحيد اللي باقي التطبيق ما بيجاوبه.
            "test.title":            .text("فحص الجسم"),
            "test.mics":             .text("المايكات"),
            "test.mics.hint":        .text("اكتم واحد، احكي، وشوف التاني لحاله بيتحرّك. لو التنين ما تحرّكوا، هي ما بتسمع. لو تحرّك المكتوم، المايكات معكوسة بالتوصيل."),
            "test.mics.noreadings":  .text("ما وصلتني قراءات من المايكات. غالبًا نسخة الفيرموير ع اللوح أقدم من هاي الميزة — احرقها من جديد."),
            "test.mic.left":         .text("المايك الشمال"),
            "test.mic.mutedValue":   .text("مكتوم"),
            "test.mic.right":        .text("المايك اليمين"),
            "test.speaker":          .text("السماعة"),
            "test.speaker.hint":     .text("اختر صوت وشغّله. بيمشي بنفس طريق صوتها الحقيقي، فلو سمعته معناها المسار كله سليم. جرّب «المسح» بالذات — سماعة بمشغّل ميت بتنجح بنغمة وحدة وبتفشل بالمسح."),
            "test.body":             .text("الوش والرقبة"),
            "test.gesture.hint":     .text("الخط فوق بيلف الرقبة لزاوية محدّدة. الحركات بتخليها تعني إشي — بتومي، بتهزّ، بتترنّح، وبترجع لمحلها لحالها."),
            "test.offline":          .text("الروبوت مش متّصل هلّق. رح تشوف آخر قراءة وصلتني، بس الأوامر ما رح توصله."),
        ],
        en: [
            "apply":          .text("Run"),
            "applied":        .text("Done — sent to the room 🏠"),
            "appliedOffline": .text("Saved the scene, but the room is offline."),
            "applyError":     .text("Couldn't apply the scene."),
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
            "saveError":      .text("Couldn't save the scene."),
            "loadError":      .text("Couldn't load your scenes. Pull to refresh."),

            // ── Body test (RobotTestView) ──
            // Reached from the node card on the Control page.
            "test.title":            .text("Body test"),
            "test.mics":             .text("Microphones"),
            "test.mics.hint":        .text("Mute one, speak, and watch the other move on its own. If neither moves, she isn't hearing you. If the muted one moves, they're wired the wrong way round."),
            "test.mics.noreadings":  .text("No microphone readings have arrived. The board is probably running firmware older than this feature — reflash it."),
            "test.mic.left":         .text("Left microphone"),
            "test.mic.mutedValue":   .text("muted"),
            "test.mic.right":        .text("Right microphone"),
            "test.speaker":          .text("Speaker"),
            "test.speaker.hint":     .text("Pick a sound and play it. It travels the same path as her real voice, so hearing it means the whole output path works. Try the sweep especially — a speaker with a dead driver passes a single tone and fails a sweep."),
            "test.body":             .text("Face and neck"),
            "test.gesture.hint":     .text("The slider above turns her neck to an angle. The gestures make it mean something — she nods, shakes, tilts, and returns home on her own."),
            "test.offline":          .text("The robot is offline right now. You'll see the last readings I got, but commands won't reach it."),
        ]
    )
}
