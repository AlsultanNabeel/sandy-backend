import Foundation

// Namespace: books — the Reading shelf. Tracks books (reading/done/want), reading
// stats over the last 30 days, a yearly goal, plus per-book notes and quotes, over
// the /api/life/books routes. Sandy's warm voice; male user → masculine forms.
enum L10nBooks {
    static let ns = "books"

    static let table = L10nTable(
        ar: [
            // الشاشة
            "title":            .text("مكتبتي"),
            "add":              .text("ضيف كتاب"),
            "empty":            .text("رفّك فارغ — أضف أول كتاب وابدأ رحلتك."),
            "errorLoad":        .text("تعذّر تحميل كتبك. أعد المحاولة."),
            "errorAdd":         .text("تعذّرت إضافة الكتاب. قد يكون الاسم مكرّرًا — جرّب اسمًا آخر."),
            "errorStatus":      .text("تعذّر تغيير حالة الكتاب. أعد المحاولة."),
            "errorMeta":        .text("تعذّر حفظ التعديل. أعد المحاولة."),
            "errorNote":        .text("تعذّر حفظ الملاحظة. أعد المحاولة."),
            "errorQuote":       .text("تعذّر حفظ الاقتباس. أعد المحاولة."),
            "errorGoal":        .text("تعذّر حفظ هدفك. أعد المحاولة."),

            // الإحصائيات (آخر ٣٠ يوم)
            "stats.title":      .text("آخر ٣٠ يوم"),
            "stats.sessions":   .text("جلسة"),
            "stats.pages":      .text("صفحة"),
            "stats.minutes":    .text("دقيقة"),
            "stats.streak":     .text("سلسلة"),
            "stats.streakDays": .text("%@ يوم متتالي"),

            // الهدف السنوي
            "goal.title":       .text("هدف السنة"),
            "goal.none":        .text("ما حطّيت هدف لهالسنة بعد — حدّد كم كتاب بدّك تخلّص وبشجّعك عليه."),
            "goal.set":         .text("حدّد هدفك"),
            "goal.edit":        .text("عدّل الهدف"),
            "goal.books":       .text("%1$@ من %2$@ كتاب"),
            "goal.pages":       .text("%1$@ من %2$@ صفحة"),

            // حالات الكتاب
            "status.reading":   .text("بقراه"),
            "status.done":      .text("خلّصته"),
            "status.wishlist":  .text("بدّي أقراه"),
            "status.section.reading":  .text("عم بقرا"),
            "status.section.wishlist": .text("قائمة الرغبات"),
            "status.section.done":     .text("خلّصتها"),

            // بطاقة الكتاب
            "card.by":          .text("لـ %@"),
            "card.progress":    .text("صفحة %1$@ من %2$@"),
            "card.notes":       .text("%@ ملاحظة"),
            "card.quotes":      .text("%@ اقتباس"),
            "card.changeStatus":.text("غيّر الحالة"),
            "card.edit":        .text("عدّل التفاصيل"),
            "card.addNote":     .text("ضيف ملاحظة"),
            "card.addQuote":    .text("ضيف اقتباس"),

            // شيت الإضافة
            "add.title":        .text("كتاب جديد"),
            "add.titleSection": .text("اسم الكتاب"),
            "add.titlePlaceholder": .text("شو اسم الكتاب؟"),
            "add.statusSection":.text("وين صرت فيه؟"),
            "add.detailsSection": .text("تفاصيل (اختياري)"),
            "add.authorPlaceholder": .text("المؤلّف"),
            "add.categoryPlaceholder": .text("التصنيف"),
            "add.pagesPlaceholder": .text("عدد الصفحات"),

            // شيت التعديل (الميتاداتا)
            "meta.title":       .text("تفاصيل الكتاب"),
            "meta.authorSection": .text("المؤلّف"),
            "meta.categorySection": .text("التصنيف"),
            "meta.pagesSection":.text("عدد الصفحات"),
            "meta.coverSection":.text("رابط الغلاف"),
            "meta.coverPlaceholder": .text("رابط صورة الغلاف"),

            // شيت الحالة
            "statusSheet.title": .text("غيّر حالة الكتاب"),
            "statusSheet.prompt": .text("وين صرت مع هالكتاب؟"),

            // شيت الملاحظة
            "noteSheet.title":  .text("ملاحظة على الكتاب"),
            "noteSheet.section":.text("شو خطر ببالك؟"),
            "noteSheet.placeholder": .text("اكتب ملاحظتك…"),

            // شيت الاقتباس
            "quoteSheet.title": .text("اقتباس من الكتاب"),
            "quoteSheet.textSection": .text("الاقتباس"),
            "quoteSheet.textPlaceholder": .text("اكتب الجملة اللي عجبتك…"),
            "quoteSheet.pageSection": .text("الصفحة (اختياري)"),
            "quoteSheet.pagePlaceholder": .text("رقم الصفحة"),

            // شيت الهدف
            "goalSheet.title":  .text("هدف القراءة السنوي"),
            "goalSheet.booksSection": .text("كم كتاب بدّك تخلّص هالسنة؟"),
            "goalSheet.booksPlaceholder": .text("عدد الكتب"),
            "goalSheet.pagesSection": .text("كم صفحة (اختياري)؟"),
            "goalSheet.pagesPlaceholder": .text("عدد الصفحات"),

            "save":             .text("احفظ"),
        ],
        en: [
            // Screen
            "title":            .text("My Library"),
            "add":              .text("Add Book"),
            "empty":            .text("Your shelf is empty — add your first book."),
            "errorLoad":        .text("Couldn't load your books. Try again."),
            "errorAdd":         .text("Couldn't add the book. The title may already exist — try another."),
            "errorStatus":      .text("Couldn't change the book's status. Try again."),
            "errorMeta":        .text("Couldn't save the changes. Try again."),
            "errorNote":        .text("Couldn't save the note. Try again."),
            "errorQuote":       .text("Couldn't save the quote. Try again."),
            "errorGoal":        .text("Couldn't save your goal. Try again."),

            // Stats (last 30 days)
            "stats.title":      .text("Last 30 days"),
            "stats.sessions":   .text("sessions"),
            "stats.pages":      .text("pages"),
            "stats.minutes":    .text("minutes"),
            "stats.streak":     .text("streak"),
            "stats.streakDays": .text("%@-day streak"),

            // Yearly goal
            "goal.title":       .text("This year's goal"),
            "goal.none":        .text("You haven't set a goal yet — pick how many books you want to finish and I'll cheer you on."),
            "goal.set":         .text("Set your goal"),
            "goal.edit":        .text("Edit goal"),
            "goal.books":       .text("%1$@ of %2$@ books"),
            "goal.pages":       .text("%1$@ of %2$@ pages"),

            // Book statuses
            "status.reading":   .text("Reading"),
            "status.done":      .text("Finished"),
            "status.wishlist":  .text("Want to read"),
            "status.section.reading":  .text("Reading now"),
            "status.section.wishlist": .text("Wishlist"),
            "status.section.done":     .text("Finished"),

            // Book card
            "card.by":          .text("by %@"),
            "card.progress":    .text("Page %1$@ of %2$@"),
            "card.notes":       .text("%@ notes"),
            "card.quotes":      .text("%@ quotes"),
            "card.changeStatus":.text("Change status"),
            "card.edit":        .text("Edit details"),
            "card.addNote":     .text("Add note"),
            "card.addQuote":    .text("Add quote"),

            // Add sheet
            "add.title":        .text("New book"),
            "add.titleSection": .text("Book title"),
            "add.titlePlaceholder": .text("What's the book called?"),
            "add.statusSection":.text("Where are you with it?"),
            "add.detailsSection": .text("Details (optional)"),
            "add.authorPlaceholder": .text("Author"),
            "add.categoryPlaceholder": .text("Category"),
            "add.pagesPlaceholder": .text("Number of pages"),

            // Edit (meta) sheet
            "meta.title":       .text("Book details"),
            "meta.authorSection": .text("Author"),
            "meta.categorySection": .text("Category"),
            "meta.pagesSection":.text("Number of pages"),
            "meta.coverSection":.text("Cover URL"),
            "meta.coverPlaceholder": .text("Cover image URL"),

            // Status sheet
            "statusSheet.title": .text("Change status"),
            "statusSheet.prompt": .text("Where are you with this book?"),

            // Note sheet
            "noteSheet.title":  .text("Note on this book"),
            "noteSheet.section":.text("What's on your mind?"),
            "noteSheet.placeholder": .text("Write your note…"),

            // Quote sheet
            "quoteSheet.title": .text("Quote from this book"),
            "quoteSheet.textSection": .text("The quote"),
            "quoteSheet.textPlaceholder": .text("Write the line you loved…"),
            "quoteSheet.pageSection": .text("Page (optional)"),
            "quoteSheet.pagePlaceholder": .text("Page number"),

            // Goal sheet
            "goalSheet.title":  .text("Yearly reading goal"),
            "goalSheet.booksSection": .text("How many books this year?"),
            "goalSheet.booksPlaceholder": .text("Number of books"),
            "goalSheet.pagesSection": .text("How many pages (optional)?"),
            "goalSheet.pagesPlaceholder": .text("Number of pages"),

            "save":             .text("Save"),
        ]
    )
}
