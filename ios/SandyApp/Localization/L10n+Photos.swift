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
            "empty":        .text("لا توجد صور محفوظة بعد — أضف أول صورة."),
            "errorLoad":    .text("تعذّر تحميل الصور. اسحب للتحديث."),
            "errorAdd":     .text("تعذّر حفظ الصورة. أعد المحاولة."),
            "errorDelete":  .text("تعذّر حذف الصورة. أعد المحاولة."),

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
            "empty":        .text("No saved photos yet — add your first one."),
            "errorLoad":    .text("Couldn't load your photos. Pull to refresh."),
            "errorAdd":     .text("Couldn't save the photo. Try again."),
            "errorDelete":  .text("Couldn't delete the photo. Try again."),

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
