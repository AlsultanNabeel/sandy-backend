import SwiftUI


/// تعريف لأي ورقة تخصّ كتابًا محدّدًا (لتمريرها لـ `.fullScreenCover(item:)`).
private struct BookSheet: Identifiable {
    enum Kind { case status, meta, note, quote }
    let id = UUID()
    let kind: Kind
    let book: BookItem
}


/// حالات الكتاب الثلاث — تطابق قيم الباك-إند الحرفية، وترتيب العرض بالرفّ.
enum BookStatus: String, CaseIterable, Identifiable {
    case reading, wishlist, done
    var id: String { rawValue }
    /// مفتاح l10n لعنوان القسم بالقائمة.
    var sectionKey: String {
        switch self {
        case .reading:  return "books.status.section.reading"
        case .wishlist: return "books.status.section.wishlist"
        case .done:     return "books.status.section.done"
        }
    }
    /// مفتاح l10n لاسم الحالة (بالمنتقيات).
    var labelKey: String { "books.status.\(rawValue)" }
}


/// سطر كتاب بالرفّ — تطابق عناصر GET /api/life/books items[].
/// المعرّف بالواجهة هو العنوان (title) لأنه مفتاح كل عمليات التعديل بالباك-إند،
/// وهو فريد (الباك-إند يرفض عنوانًا متكرّرًا عند الإضافة).
struct BookItem: Identifiable {
    let title: String
    let author: String
    let category: String
    let coverURL: String
    let status: String        // "reading" | "done" | "wishlist"
    let totalPages: Int
    let currentPage: Int
    let rating: Int           // 0..5
    let fmt: String           // "paper" | "ebook" | "audio" | ""
    let notesCount: Int
    let quotesCount: Int

    var id: String { title }
}


/// إحصائيات القراءة لآخر فترة — تطابق كائن stats من GET /api/life/books.
struct BookStats {
    var sessions: Int = 0
    var pages: Int = 0
    var minutes: Int = 0
    var pagesPerDay: Int = 0
    var streakDays: Int = 0
}


/// تقدّم هدف القراءة السنوي — تطابق كائن goal من GET /api/life/books.
struct BookGoal {
    var booksYear: Int = 0    // الهدف (عدد كتب)
    var pagesYear: Int = 0    // الهدف (عدد صفحات)
    var booksDone: Int = 0    // المنجز فعلاً هالسنة
    var pagesRead: Int = 0    // المقروء فعلاً هالسنة

    /// في هدف محدّد لو على الأقل أحد الهدفين موجب.
    var hasTarget: Bool { booksYear > 0 || pagesYear > 0 }
}


/// نتيجة جلب الرفّ كاملة: العناصر + الإحصائيات + الهدف + علامة التجربة.
struct BooksResult {
    let items: [BookItem]
    let stats: BookStats
    let goal: BookGoal
    let demo: Bool
}
