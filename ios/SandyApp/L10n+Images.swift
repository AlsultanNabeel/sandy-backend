import Foundation

// Namespace: images — the Images tab. Generate (Azure FLUX) via /api/image, edit
// via /api/image/edit, describe via /api/analyze-image.
enum L10nImages {
    static let ns = "images"

    static let table = L10nTable(
        ar: [
            "mode.generate": .text("توليد"),
            "mode.edit":     .text("تعديل"),
            "mode.describe": .text("وصف"),

            "promptPlaceholder":   .text("وصّفلي الصورة اللي بدك ياها…"),
            "editPlaceholder":     .text("شو بدك أعدّل بالصورة؟"),
            "questionPlaceholder": .text("سؤال عن الصورة (اختياري)"),

            "generate": .text("ولّد الصورة"),
            "edit":     .text("عدّل الصورة"),
            "describe": .text("صِف الصورة"),

            "pick":      .text("اختر صورة"),
            "pickAgain": .text("اختر صورة ثانية"),
            "share":     .text("مشاركة"),

            "error": .text("معلش، ما قدرت أكمّل — جرّب كمان مرة."),
        ],
        en: [
            "mode.generate": .text("Generate"),
            "mode.edit":     .text("Edit"),
            "mode.describe": .text("Describe"),

            "promptPlaceholder":   .text("Describe the image you want…"),
            "editPlaceholder":     .text("What should I change?"),
            "questionPlaceholder": .text("A question about the image (optional)"),

            "generate": .text("Generate image"),
            "edit":     .text("Edit image"),
            "describe": .text("Describe image"),

            "pick":      .text("Pick a photo"),
            "pickAgain": .text("Pick another"),
            "share":     .text("Share"),

            "error": .text("Sorry, I couldn't finish — try again."),
        ]
    )
}
