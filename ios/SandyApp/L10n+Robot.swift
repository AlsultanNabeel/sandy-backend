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
        ]
    )
}
