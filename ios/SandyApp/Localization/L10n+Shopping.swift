import Foundation

// Namespace: shopping — قائمة التسوّق. تسرد العناصر، تضيف، تشطب (انشترى)،
// تحذف، تحدّد سعر/كمية، وتعرض آخر سعر مدفوع — فوق /api/life/shopping.
enum L10nShopping {
    static let ns = "shopping"

    static let table = L10nTable(
        ar: [
            "title":            .text("قائمة التسوّق"),
            "intro":            .text("كل اللي ناوي تجيبه بمكان واحد — اشطب اللي اشتريته وسجّل سعره فبضل معك."),
            "add":              .text("ضيف غرض"),
            "empty":            .text("القائمة فاضية — ضيف أول غرض وأنا بظبّطلك إياها."),
            "edit":             .text("تعديل"),
            "delete":           .text("حذف"),
            "buy":              .text("اشتريته"),
            "unbuy":            .text("رجّعه للقائمة"),
            "bought":           .text("انشترى"),
            "noCategory":       .text("بدون تصنيف"),
            "qty":              .text("الكمية"),
            "price":            .text("السعر"),
            // %@ = آخر سعر مدفوع (رقم).
            "lastPrice":        .text("آخر سعر: %@"),
            // %@ = الإجمالي التقديري (سعر × كمية).
            "estTotal":         .text("≈ %@"),

            "addTitle":         .text("غرض جديد"),
            "editTitle":        .text("تعديل الغرض"),
            "sheet.namePrompt": .text("شو بدك تجيب؟"),
            "sheet.namePlaceholder": .text("مثلاً: حليب، خبز، قهوة…"),
            "sheet.categoryPrompt":  .text("التصنيف (اختياري)"),
            "sheet.categoryPlaceholder": .text("مثلاً: بقالة، خضار وفواكه…"),
            "sheet.qtyPrompt":  .text("الكمية والسعر للوحدة (اختياري)"),
            "sheet.pricePlaceholder": .text("سعر الوحدة"),
            "saveNew":          .text("ضيف للقائمة"),
            "saveEdit":         .text("احفظ التعديل"),

            "priceTitle":       .text("سجّل الشراء"),
            "pricePrompt":      .text("قدّيش دفعت؟ بسجّله بمصاريفك تلقائياً."),
            "priceSave":        .text("سجّل واشطب"),

            "errorLoad":        .text("معلش، ما قدرت أجيب القائمة — جرّب كمان مرة."),
            "errorAdd":         .text("ما زبط أضيف الغرض — يمكن موجود من قبل، جرّب كمان مرة."),
            "errorEdit":        .text("ما قدرت أحفظ التعديل — جرّب كمان مرة."),
            "errorDelete":      .text("ما قدرت أحذف الغرض — جرّب كمان مرة."),
            "errorBuy":         .text("ما قدرت أشطب الغرض — جرّب كمان مرة."),
        ],
        en: [
            "title":            .text("Shopping list"),
            "intro":            .text("Everything you need in one place — check off what you bought and I'll keep its price for next time."),
            "add":              .text("Add item"),
            "empty":            .text("Your list is empty — add the first item and I'll keep it tidy."),
            "edit":             .text("Edit"),
            "delete":           .text("Delete"),
            "buy":              .text("Bought it"),
            "unbuy":            .text("Back to list"),
            "bought":           .text("Bought"),
            "noCategory":       .text("No category"),
            "qty":              .text("Qty"),
            "price":            .text("Price"),
            "lastPrice":        .text("Last price: %@"),
            "estTotal":         .text("≈ %@"),

            "addTitle":         .text("New item"),
            "editTitle":        .text("Edit item"),
            "sheet.namePrompt": .text("What do you need?"),
            "sheet.namePlaceholder": .text("e.g. milk, bread, coffee…"),
            "sheet.categoryPrompt":  .text("Category (optional)"),
            "sheet.categoryPlaceholder": .text("e.g. groceries, produce…"),
            "sheet.qtyPrompt":  .text("Quantity and unit price (optional)"),
            "sheet.pricePlaceholder": .text("Unit price"),
            "saveNew":          .text("Add to list"),
            "saveEdit":         .text("Save changes"),

            "priceTitle":       .text("Log purchase"),
            "pricePrompt":      .text("How much did you pay? I'll log it to your expenses automatically."),
            "priceSave":        .text("Log & check off"),

            "errorLoad":        .text("Sorry, I couldn't load the list — try again."),
            "errorAdd":         .text("Couldn't add the item — it may already be there, try again."),
            "errorEdit":        .text("Couldn't save the change — try again."),
            "errorDelete":      .text("Couldn't delete the item — try again."),
            "errorBuy":         .text("Couldn't check off the item — try again."),
        ]
    )
}
