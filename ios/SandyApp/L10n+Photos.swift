import Foundation

// Namespace: photos — the Album tool screen (saved photos with smart tags). Real
// photos from /api/photos; bytes streamed per-photo from /api/photos/<id>/file.
// Albums are tags in the flat schema. Decoupled from Telegram — upload is base64.
enum L10nPhotos {
    static let ns = "photos"

    static let table = L10nTable(
        ar: [
            "title":        .text("الألبوم"),
            "intro":        .text("صورك المحفوظة عند ساندي — بتوصفها وبتوسمها لحالها عشان تلاقيها بسهولة."),
            "empty":        .text("لسّا ما في صور محفوظة — أضف أول صورة وأنا بظبّطلك الوصف والوسوم."),
            "errorLoad":    .text("معلش، ما قدرت أجيب الصور — اسحب للتحديث."),
            "errorAdd":     .text("معلش، ما قدرت أحفظ الصورة — جرّب كمان مرة."),
            "errorDelete":  .text("معلش، ما قدرت أحذف الصورة — جرّب كمان مرة."),

            // أزرار وإجراءات
            "add":          .text("إضافة صورة"),
            "delete":       .text("حذف"),
            "searchPlaceholder": .text("دوّر عن صورة بالوصف أو الوسم…"),
            "allAlbums":    .text("الكل"),

            // ورقة الإضافة
            "addTitle":     .text("صورة جديدة"),
            "pick":         .text("اختر صورة"),
            "pickAgain":    .text("اختر صورة ثانية"),
            "namePrompt":   .text("سمِّ الصورة (اختياري)"),
            "namePlaceholder": .text("مثلاً: رحلة العقبة"),
            "albumPrompt":  .text("ألبوم (اختياري)"),
            "albumPlaceholder": .text("مثلاً: عائلة، سفر، شغل…"),
            "save":         .text("احفظها"),
        ],
        en: [
            "title":        .text("Album"),
            "intro":        .text("Your photos saved with Sandy — she captions and tags them so you find them easily."),
            "empty":        .text("No saved photos yet — add your first one and I'll sort out the caption and tags."),
            "errorLoad":    .text("Sorry, I couldn't load your photos — pull to refresh."),
            "errorAdd":     .text("Sorry, I couldn't save that photo — give it another try."),
            "errorDelete":  .text("Sorry, I couldn't delete that photo — try again."),

            // buttons & actions
            "add":          .text("Add photo"),
            "delete":       .text("Delete"),
            "searchPlaceholder": .text("Search photos by caption or tag…"),
            "allAlbums":    .text("All"),

            // add sheet
            "addTitle":     .text("New photo"),
            "pick":         .text("Pick a photo"),
            "pickAgain":    .text("Pick another"),
            "namePrompt":   .text("Name it (optional)"),
            "namePlaceholder": .text("e.g. Aqaba trip"),
            "albumPrompt":  .text("Album (optional)"),
            "albumPlaceholder": .text("e.g. family, travel, work…"),
            "save":         .text("Save it"),
        ]
    )
}
