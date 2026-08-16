import Foundation

// Namespace: control — the Home control surface (ControlView): devices, nodes,
// pairing, and add/edit sheets over the registry API. Mirrors the web
// dict/<ns>.js shape (kept flat). Strings live ONLY here (ar + en).
//
// Usage:  Text(lang.s("control.title"))
//         Text(String(format: lang.s("control.node.outputs"), "\(n)"))   // %@ format keys
//
// NOTES on format keys (filled in code via String(format:)):
//   "node.outputs"      → count of outputs            (one %@)
//   "device.lastSeen"   → relative time string        (one %@)
enum L10nControl {
    static let ns = "control"

    static let table = L10nTable(
        ar: [
            // ── Entry point + screen ──
            "title":            .text("التحكّم بالبيت"),
            "home.cardTitle":   .text("التحكّم بالبيت"),
            "home.cardBody":    .text("شغّل النور، سكّر الستارة، تحكّم بأجهزتك… كلها من هون."),

            // ── Sections ──
            "section.devices":  .text("أجهزتك"),
            "section.nodes":    .text("وحدات ساندي"),

            // ── Loading / empty / offline ──
            "loading":          .text("جارٍ تحميل أجهزتك…"),
            "devices.empty.title": .text("لا توجد أجهزة بعد"),
            "devices.empty.hint":  .text("اقترن بوحدة ساندي وأضف أول جهاز."),
            "nodes.empty.title":   .text("لا توجد وحدات مقترنة"),
            "nodes.empty.hint":    .text("أدخل الكود المطبوع على الوحدة لاقترانها."),
            "offline":          .text("مفصولة"),
            "online":           .text("متّصلة"),
            "noRoom":           .text("بدون غرفة"),

            // ── Generic notices (Sandy voice) ──
            "loadFailed":   .text("تعذّر تحميل أجهزتك. اسحب للتحديث."),
            "controlFailed":.text("تعذّر تنفيذ الأمر. أعد المحاولة بعد قليل."),
            "saveFailed":   .text("تعذّر الحفظ. أعد المحاولة بعد قليل."),
            "deleteFailed": .text("تعذّر الحذف. أعد المحاولة."),

            // ── Control widget labels ──
            "action.on":     .text("شغّل"),
            "action.off":    .text("طفّي"),
            "action.open":   .text("افتح"),
            "action.close":  .text("سكّر"),
            "action.stop":   .text("وقّف"),
            "action.pause":  .text("ثبّت"),
            "action.play":   .text("شغّل"),
            "dimmer.level":  .text("الإضاءة"),

            // ── Add / edit device sheet ──
            "device.add":        .text("إضافة جهاز"),
            "device.addTitle":   .text("جهاز جديد"),
            "device.editTitle":  .text("تعديل الجهاز"),
            "device.header":     .text("شو الجهاز اللي حابب تتحكّم فيه؟"),
            "device.delete":     .text("حذف"),
            "device.edit":       .text("تعديل"),

            "field.label":       .text("الاسم"),
            "field.labelPlaceholder": .text("مثلاً: نور الصالة"),
            "field.room":        .text("الغرفة (اختياري)"),
            "field.roomPlaceholder":  .text("مثلاً: الصالة"),
            "field.type":        .text("نوع التحكّم"),
            "field.transport":   .text("طريقة الوصل"),

            // Control types (display labels)
            "type.switch":  .text("مفتاح"),
            "type.dimmer":  .text("إضاءة متدرّجة"),
            "type.enum":    .text("خيارات"),
            "type.media":   .text("وسائط"),
            "type.cover":   .text("ستارة"),
            "type.ir":      .text("ريموت"),

            // Transport picker
            "transport.node":    .text("وحدة ساندي"),
            "transport.mqtt":    .text("متقدّم (إم كيو تي تي)"),
            "transport.pickNode":.text("اختر الوحدة"),
            "transport.pickOutput":.text("اختر المخرج"),
            "transport.topicPlaceholder": .text("مثلاً: home/livingroom/light"),
            "transport.needNode":.text("اربط وحدة ساندي أول حتى تقدر توصل الجهاز فيها."),

            // Type-specific meta
            "meta.enumValues":   .text("الخيارات (افصلها بفاصلة)"),
            "meta.enumPlaceholder": .text("مثلاً: بطيء، متوسّط، سريع"),
            "meta.dimmerMin":    .text("أقل قيمة"),
            "meta.dimmerMax":    .text("أعلى قيمة"),

            // IR learn
            "ir.buttons":        .text("أزرار الريموت"),
            "ir.learnPlaceholder":.text("اسم الزر (مثلاً: تشغيل)"),
            "ir.learnHint":      .text("اكتب اسم الزر وأنا أحفظه — التقاط الكود بيجي مع تحديث الوحدة لاحقًا."),
            "ir.noButtons":      .text("لا توجد أزرار محفوظة."),
            "ir.learnNew":       .text("علّم زر جديد"),
            "ir.learnStart":     .text("ابدأ"),
            "ir.learning":       .text("وجّه الريموت للوحدة واضغط الزر…"),
            "ir.learnAlertHint": .text("اكتب اسم الزر، وبعد ما تضغط ابدأ وجّه ريموتك للوحدة واضغط الزر المطلوب."),
            "ir.needNode":       .text("اربط الجهاز بوحدة أول عشان أتعلّم الأشعة."),
            "ir.learnTimeout":   .text("ما وصلتني إشارة — جرّب ثانية وقرّب الريموت."),
            "ir.learnFailed":    .text("تعذّر التعلّم. أعد المحاولة."),

            // ── Pair / rename / unpair node sheet ──
            "node.pair":         .text("ربط وحدة"),
            "node.pairTitle":    .text("ربط وحدة ساندي"),
            "node.pairHeader":   .text("اكتب الكود المطبوع على الوحدة وأنا أربطها."),
            "node.code":         .text("كود الوحدة"),
            "node.codePlaceholder":.text("مثلاً: 8421"),
            "node.labelField":   .text("اسم الوحدة (اختياري)"),
            "node.labelPlaceholder":.text("مثلاً: وحدة الصالة"),
            "node.pairSubmit":   .text("اربط"),
            "node.already":      .text("الوحدة مربوطة عندك من قبل — حدّثتلك بياناتها."),
            "node.pairFailed":   .text("الكود غير صحيح. تحقّق منه وأعد المحاولة."),
            "node.rename":       .text("إعادة تسمية"),
            "node.renameTitle":  .text("تعديل اسم الوحدة"),
            "node.unpair":       .text("فكّ الربط"),
            // format: %@ = count of outputs
            "node.outputs":      .text("%@ مخارج"),

            // common
            "save":     .text("حفظ"),
            "text.send": .text("إرسال"),
            "text.dismiss": .text("شيله عن الشاشة"),
            "unknownType": .text("نوع تحكّم (%@) ما بيعرفه هاد الإصدار من التطبيق. حدّثه."),
        ],
        en: [
            // ── Entry point + screen ──
            "title":            .text("Home control"),
            "home.cardTitle":   .text("Home control"),
            "home.cardBody":    .text("Turn on the lights, close the curtains, control your devices… all from here."),

            // ── Sections ──
            "section.devices":  .text("Your devices"),
            "section.nodes":    .text("Sandy nodes"),

            // ── Loading / empty / offline ──
            "loading":          .text("Loading your devices…"),
            "devices.empty.title": .text("No devices yet"),
            "devices.empty.hint":  .text("Pair a Sandy node and add your first device."),
            "nodes.empty.title":   .text("No paired nodes"),
            "nodes.empty.hint":    .text("Enter the code printed on the node to pair it."),
            "offline":          .text("Offline"),
            "online":           .text("Online"),
            "noRoom":           .text("No room"),

            // ── Generic notices (Sandy voice) ──
            "loadFailed":   .text("Couldn't load your devices. Pull to refresh."),
            "controlFailed":.text("The command didn't go through. Try again in a moment."),
            "saveFailed":   .text("Couldn't save. Try again in a moment."),
            "deleteFailed": .text("Couldn't delete. Try again."),

            // ── Control widget labels ──
            "action.on":     .text("On"),
            "action.off":    .text("Off"),
            "action.open":   .text("Open"),
            "action.close":  .text("Close"),
            "action.stop":   .text("Stop"),
            "action.pause":  .text("Pause"),
            "action.play":   .text("Play"),
            "dimmer.level":  .text("Brightness"),

            // ── Add / edit device sheet ──
            "device.add":        .text("Add device"),
            "device.addTitle":   .text("New device"),
            "device.editTitle":  .text("Edit device"),
            "device.header":     .text("What device would you like to control?"),
            "device.delete":     .text("Delete"),
            "device.edit":       .text("Edit"),

            "field.label":       .text("Name"),
            "field.labelPlaceholder": .text("e.g. Living room light"),
            "field.room":        .text("Room (optional)"),
            "field.roomPlaceholder":  .text("e.g. Living room"),
            "field.type":        .text("Control type"),
            "field.transport":   .text("Connection"),

            // Control types (display labels)
            "type.switch":  .text("Switch"),
            "type.dimmer":  .text("Dimmer"),
            "type.enum":    .text("Options"),
            "type.media":   .text("Media"),
            "type.cover":   .text("Cover"),
            "type.ir":      .text("Remote"),

            // Transport picker
            "transport.node":    .text("Sandy node"),
            "transport.mqtt":    .text("Advanced (MQTT)"),
            "transport.pickNode":.text("Pick a node"),
            "transport.pickOutput":.text("Pick an output"),
            "transport.topicPlaceholder": .text("e.g. home/livingroom/light"),
            "transport.needNode":.text("Pair a Sandy node first so you can connect the device to it."),

            // Type-specific meta
            "meta.enumValues":   .text("Options (comma separated)"),
            "meta.enumPlaceholder": .text("e.g. low, medium, high"),
            "meta.dimmerMin":    .text("Min value"),
            "meta.dimmerMax":    .text("Max value"),

            // IR learn
            "ir.buttons":        .text("Remote buttons"),
            "ir.learnPlaceholder":.text("Button name (e.g. Power)"),
            "ir.learnHint":      .text("Type the button name and I'll save it — code capture comes with a node update later."),
            "ir.noButtons":      .text("No saved buttons."),
            "ir.learnNew":       .text("Learn a new button"),
            "ir.learnStart":     .text("Start"),
            "ir.learning":       .text("Point the remote at the node and press the button…"),
            "ir.learnAlertHint": .text("Name the button, then after you tap Start point your remote at the node and press it."),
            "ir.needNode":       .text("Bind this device to a node first so I can learn IR."),
            "ir.learnTimeout":   .text("No signal received — try again, closer."),
            "ir.learnFailed":    .text("Couldn't learn it. Try again."),

            // ── Pair / rename / unpair node sheet ──
            "node.pair":         .text("Pair a node"),
            "node.pairTitle":    .text("Pair a Sandy node"),
            "node.pairHeader":   .text("Enter the code printed on the node and I'll pair it."),
            "node.code":         .text("Node code"),
            "node.codePlaceholder":.text("e.g. 8421"),
            "node.labelField":   .text("Node name (optional)"),
            "node.labelPlaceholder":.text("e.g. Living room node"),
            "node.pairSubmit":   .text("Pair"),
            "node.already":      .text("This node was already paired — I refreshed its details for you."),
            "node.pairFailed":   .text("That code isn't valid. Check it and try again."),
            "node.rename":       .text("Rename"),
            "node.renameTitle":  .text("Edit node name"),
            "node.unpair":       .text("Unpair"),
            // format: %@ = count of outputs
            "node.outputs":      .text("%@ outputs"),

            // common
            "save":     .text("Save"),
            "text.send": .text("Send"),
            "text.dismiss": .text("Take it off the screen"),
            "unknownType": .text("A control type (%@) this version of the app does not know. Update it."),
        ]
    )
}
