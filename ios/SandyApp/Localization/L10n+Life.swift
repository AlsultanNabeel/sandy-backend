import Foundation

// Namespace: life — habits / expenses / journal screen. FILLED by the LifeView
// migration agent (ar + en).
//
// Usage:  Text(lang.s("life.habits"))
//
// CANONICAL EXPENSE CATEGORIES — IMPORTANT CONTRACT:
//   The backend stores/receives the *Arabic* category string as-is (e.g. "أكل").
//   That Arabic value is the stable canonical value and MUST keep being sent.
//   For DISPLAY only we map a canonical Arabic value → a localized label via the
//   "cat.*" keys below. AddExpenseSheet picks from canonical values and shows
//   lang.s("life.cat.<…>"); ExpensesView renders a stored category by mapping the
//   same canonical value back to a localized label (LifeCategories.label(for:)).
//   Never send the localized label to the API.
enum L10nLife {
    static let ns = "life"

    static let table = L10nTable(
        ar: [
            // Hub
            "title":              .text("حياتي"),
            "habits":             .text("العادات"),
            "expenses":           .text("المصاريف"),
            "journal":            .text("اليوميات"),
            "gifts":              .text("الهدايا الرقمية"),
            "gifts.subtitle":     .text("هدايا صغيرة لمن تحب"),
            "expenses.subtitle":  .text("سجّل مصاريفك وشوف المجموع"),
            "journal.subtitle":   .text("دوّن يومك"),

            // Habits screen
            "habits.add":         .text("عادة جديدة"),
            "habits.empty":       .text("لا توجد عادات بعد.\nابدأ عادة جديدة."),
            "habits.streak":      .text("🔥 %@ يوم"),
            "habits.doneToday":   .text("تمّت اليوم ✓"),
            "habits.loadError":   .text("تعذّر تحميل العادات. أعد المحاولة بعد قليل."),
            "habits.checkinError": .text("تعذّر تسجيل الحضور. أعد المحاولة."),

            // Add-habit sheet
            "habits.sheet.nameSection":  .text("شو العادة؟"),
            "habits.sheet.namePlaceholder": .text("مثلاً: قراءة ٢٠ دقيقة"),
            "habits.sheet.freqSection":  .text("كل قدّيش؟"),
            "habits.sheet.freqLabel":    .text("التكرار"),
            "habits.freq.daily":         .text("كل يوم"),
            "habits.freq.weekly":        .text("كل أسبوع"),
            "habits.sheet.weeklySuffix": .text("(أسبوعي)"),
            "habits.saveError":          .text("تعذّر حفظ العادة. أعد المحاولة."),
            "habits.edit":               .text("تعديل"),
            "habits.delete":             .text("حذف"),
            "habits.editTitle":          .text("تعديل العادة"),
            "habits.deleteError":        .text("تعذّر حذف العادة. أعد المحاولة."),

            // Expenses screen
            "expenses.add":            .text("أضف مصروف"),
            "expenses.empty":          .text("لا توجد مصاريف مسجّلة.\nسجّل أول مصروف."),
            "expenses.summaryTitle":   .text("مصاريف آخر ٣٠ يوم"),
            "expenses.count":          .text("%@ حركة"),
            "expenses.fallbackTitle":  .text("مصروف"),
            "expenses.loadError":      .text("تعذّر تحميل المصاريف. أعد المحاولة بعد قليل."),

            // Add-expense sheet
            "expenses.sheet.amountSection":  .text("المبلغ"),
            "expenses.sheet.amountPlaceholder": .text("0"),
            "expenses.sheet.categorySection": .text("التصنيف"),
            "expenses.sheet.categoryLabel":  .text("التصنيف"),
            "expenses.sheet.noteSection":    .text("ملاحظة (اختياري)"),
            "expenses.sheet.notePlaceholder": .text("مثلاً: غدا مع الشباب"),
            "expenses.sheet.title":          .text("مصروف جديد"),
            "expenses.sheet.editTitle":      .text("تعديل المصروف"),
            "expenses.amountError":          .text("اكتب مبلغ أكبر من صفر أوّل 🙂"),
            "expenses.saveError":            .text("تعذّر حفظ المصروف. أعد المحاولة."),
            "expenses.edit":                 .text("تعديل"),
            "expenses.delete":               .text("حذف"),
            "expenses.deleteError":          .text("تعذّر حذف المصروف. أعد المحاولة."),

            // Expense categories — labels for display only (canonical = Arabic value)
            "cat.food":      .text("أكل"),
            "cat.transport": .text("مواصلات"),
            "cat.shopping":  .text("تسوّق"),
            "cat.bills":     .text("فواتير"),
            "cat.fun":       .text("ترفيه"),
            "cat.other":     .text("أخرى"),

            // Journal screen
            "journal.add":        .text("خاطرة جديدة"),
            "journal.empty":      .text("لا توجد خواطر بعد.\nاكتب أول خاطرة."),
            "journal.loadError":  .text("تعذّر تحميل اليوميات. أعد المحاولة بعد قليل."),

            // Add-journal sheet
            "journal.sheet.section":      .text("شو صار اليوم؟"),
            "journal.sheet.placeholder":  .text("اكتب خاطرتك… خذ راحتك"),
            "journal.sheet.charCount":    .text("%@ حرف"),
            "journal.sheet.title":        .text("خاطرة جديدة"),
            "journal.sheet.editTitle":    .text("تعديل الخاطرة"),
            "journal.saveError":          .text("تعذّر حفظ الخاطرة. أعد المحاولة."),
            "journal.edit":               .text("تعديل"),
            "journal.delete":             .text("حذف"),
            "journal.deleteError":        .text("تعذّر حذف الخاطرة. أعد المحاولة."),
        ],
        en: [
            // Hub
            "title":              .text("My Life"),
            "habits":             .text("Habits"),
            "expenses":           .text("Expenses"),
            "journal":            .text("Journal"),
            "gifts":              .text("Digital gifts"),
            "gifts.subtitle":     .text("Little gifts for the ones you love"),
            "expenses.subtitle":  .text("Log spending and see the total"),
            "journal.subtitle":   .text("Write down your day"),

            // Habits screen
            "habits.add":         .text("New habit"),
            "habits.empty":       .text("No habits yet.\nStart a new one."),
            "habits.streak":      .text("🔥 %@ days"),
            "habits.doneToday":   .text("Done today ✓"),
            "habits.loadError":   .text("Couldn't load your habits. Try again shortly."),
            "habits.checkinError": .text("Couldn't log the check-in. Try again."),

            // Add-habit sheet
            "habits.sheet.nameSection":  .text("What's the habit?"),
            "habits.sheet.namePlaceholder": .text("e.g. Read for 20 minutes"),
            "habits.sheet.freqSection":  .text("How often?"),
            "habits.sheet.freqLabel":    .text("Frequency"),
            "habits.freq.daily":         .text("Every day"),
            "habits.freq.weekly":        .text("Every week"),
            "habits.sheet.weeklySuffix": .text("(weekly)"),
            "habits.saveError":          .text("Couldn't save the habit. Try again."),
            "habits.edit":               .text("Edit"),
            "habits.delete":             .text("Delete"),
            "habits.editTitle":          .text("Edit habit"),
            "habits.deleteError":        .text("Couldn't delete the habit. Try again."),

            // Expenses screen
            "expenses.add":            .text("Add expense"),
            "expenses.empty":          .text("No expenses recorded.\nAdd your first one."),
            "expenses.summaryTitle":   .text("Last 30 days"),
            "expenses.count":          .text("%@ entries"),
            "expenses.fallbackTitle":  .text("Expense"),
            "expenses.loadError":      .text("Couldn't load your expenses. Try again shortly."),

            // Add-expense sheet
            "expenses.sheet.amountSection":  .text("Amount"),
            "expenses.sheet.amountPlaceholder": .text("0"),
            "expenses.sheet.categorySection": .text("Category"),
            "expenses.sheet.categoryLabel":  .text("Category"),
            "expenses.sheet.noteSection":    .text("Note (optional)"),
            "expenses.sheet.notePlaceholder": .text("e.g. Lunch with friends"),
            "expenses.sheet.title":          .text("New expense"),
            "expenses.sheet.editTitle":      .text("Edit expense"),
            "expenses.amountError":          .text("Enter an amount above zero first 🙂"),
            "expenses.saveError":            .text("Couldn't save the expense. Try again."),
            "expenses.edit":                 .text("Edit"),
            "expenses.delete":               .text("Delete"),
            "expenses.deleteError":          .text("Couldn't delete the expense. Try again."),

            // Expense categories — labels for display only (canonical = Arabic value)
            "cat.food":      .text("Food"),
            "cat.transport": .text("Transport"),
            "cat.shopping":  .text("Shopping"),
            "cat.bills":     .text("Bills"),
            "cat.fun":       .text("Fun"),
            "cat.other":     .text("Other"),

            // Journal screen
            "journal.add":        .text("New entry"),
            "journal.empty":      .text("No entries yet.\nWrite your first one."),
            "journal.loadError":  .text("Couldn't load your journal. Try again shortly."),

            // Add-journal sheet
            "journal.sheet.section":      .text("How was your day?"),
            "journal.sheet.placeholder":  .text("Write your entry… take your time"),
            "journal.sheet.charCount":    .text("%@ chars"),
            "journal.sheet.title":        .text("New entry"),
            "journal.sheet.editTitle":    .text("Edit entry"),
            "journal.saveError":          .text("Couldn't save the entry. Try again."),
            "journal.edit":               .text("Edit"),
            "journal.delete":             .text("Delete"),
            "journal.deleteError":        .text("Couldn't delete the entry. Try again."),
        ]
    )
}

// MARK: - Expense category canonical ↔ label mapping
//
// The CANONICAL value is the Arabic string the backend stores/receives (kept
// exactly as before this migration, so old records and the API contract stay
// intact). The picker offers canonical values; the UI shows a localized label.
enum LifeCategories {
    /// The canonical category values, in display order. First is the default.
    /// These Arabic strings are what gets sent to the backend — DO NOT translate.
    static let canonical: [String] = ["أكل", "مواصلات", "تسوّق", "فواتير", "ترفيه", "أخرى"]

    /// "Other" canonical value — the sheet maps it to an empty category on save
    /// (unchanged behavior).
    static let other = "أخرى"

    /// Map a canonical Arabic value to its localized-label key.
    private static func key(for canonical: String) -> String {
        switch canonical {
        case "أكل":      return "life.cat.food"
        case "مواصلات":  return "life.cat.transport"
        case "تسوّق":    return "life.cat.shopping"
        case "فواتير":   return "life.cat.bills"
        case "ترفيه":    return "life.cat.fun"
        case "أخرى":     return "life.cat.other"
        default:          return ""
        }
    }

    /// Localized display label for a stored/canonical category value.
    /// Unknown values (free-text from the backend) are returned as-is.
    @MainActor
    static func label(for canonical: String, _ lang: LanguageManager) -> String {
        let k = key(for: canonical)
        return k.isEmpty ? canonical : lang.s(k)
    }
}
