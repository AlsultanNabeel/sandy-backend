import SwiftUI


/// ورقة إضافة كتاب جديد: العنوان (إلزامي) + الحالة + تفاصيل اختيارية
/// (مؤلّف/تصنيف/صفحات). تُرسل عبر closure غير متزامن يرجّع نجاح/فشل ليتقرّر الإغلاق.
private struct BookAddSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    let onSubmit: (_ title: String, _ status: String, _ author: String,
                   _ category: String, _ totalPages: Int) async -> Bool

    @State private var title = ""
    @State private var status: BookStatus = .reading
    @State private var author = ""
    @State private var category = ""
    @State private var pages = ""
    @State private var submitting = false

    private var trimmedTitle: String { title.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        SandyPopup(title: lang.s("books.add.title")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("books.add.titleSection"))
                    SandyCard {
                        TextField(lang.s("books.add.titlePlaceholder"), text: $title)
                            .font(Theme.Typography.body)
                    }
                }
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("books.add.statusSection"))
                    Picker(lang.s("books.add.statusSection"), selection: $status) {
                        ForEach(BookStatus.allCases) { s in
                            Text(lang.s(s.labelKey)).tag(s)
                        }
                    }
                    .pickerStyle(.segmented)
                }
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("books.add.detailsSection"))
                    SandyCard {
                        TextField(lang.s("books.add.authorPlaceholder"), text: $author)
                            .font(Theme.Typography.body)
                    }
                    SandyCard {
                        TextField(lang.s("books.add.categoryPlaceholder"), text: $category)
                            .font(Theme.Typography.body)
                    }
                    SandyCard {
                        TextField(lang.s("books.add.pagesPlaceholder"), text: $pages)
                            .keyboardType(.numberPad)
                            .font(Theme.Typography.body)
                    }
                }
                SandyButton(title: lang.s("books.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
                .disabled(trimmedTitle.isEmpty)
                .opacity(trimmedTitle.isEmpty ? 0.5 : 1)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard !trimmedTitle.isEmpty, !submitting else { return }
        submitting = true
        Task {
            let ok = await onSubmit(trimmedTitle, status.rawValue,
                                    author.trimmingCharacters(in: .whitespaces),
                                    category.trimmingCharacters(in: .whitespaces),
                                    Int(pages.trimmingCharacters(in: .whitespaces)) ?? 0)
            submitting = false
            if ok { dismiss() }
        }
    }
}


/// ورقة تغيير حالة كتاب — منتقي بين الحالات الثلاث.
private struct BookStatusSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    let current: String
    let onSubmit: (_ status: String) async -> Bool

    @State private var status: BookStatus
    @State private var submitting = false

    init(current: String, onSubmit: @escaping (_ status: String) async -> Bool) {
        self.current = current
        self.onSubmit = onSubmit
        _status = State(initialValue: BookStatus(rawValue: current) ?? .reading)
    }

    var body: some View {
        SandyPopup(title: lang.s("books.statusSheet.title")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                SectionHeader(title: lang.s("books.statusSheet.prompt"))
                Picker(lang.s("books.statusSheet.prompt"), selection: $status) {
                    ForEach(BookStatus.allCases) { s in
                        Text(lang.s(s.labelKey)).tag(s)
                    }
                }
                .pickerStyle(.segmented)
                SandyButton(title: lang.s("books.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard !submitting else { return }
        submitting = true
        Task {
            let ok = await onSubmit(status.rawValue)
            submitting = false
            if ok { dismiss() }
        }
    }
}


/// ورقة تعديل ميتاداتا الكتاب: مؤلّف/تصنيف/عدد صفحات/رابط غلاف. كل حقل اختياري —
/// نرسل فقط الحقول اللي تغيّرت عن قيمتها الأصلية (تطابق additive meta بالباك-إند).
private struct BookMetaSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    let book: BookItem
    /// يستقبل القيم الاختيارية (nil = بلا تغيير) ويرجّع نجاح/فشل.
    let onSubmit: (_ author: String?, _ category: String?,
                   _ totalPages: Int?, _ coverURL: String?) async -> Bool

    @State private var author: String
    @State private var category: String
    @State private var pages: String
    @State private var cover: String
    @State private var submitting = false

    init(book: BookItem,
         onSubmit: @escaping (_ author: String?, _ category: String?,
                              _ totalPages: Int?, _ coverURL: String?) async -> Bool) {
        self.book = book
        self.onSubmit = onSubmit
        _author = State(initialValue: book.author)
        _category = State(initialValue: book.category)
        _pages = State(initialValue: book.totalPages > 0 ? String(book.totalPages) : "")
        _cover = State(initialValue: book.coverURL)
    }

    var body: some View {
        SandyPopup(title: lang.s("books.meta.title")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                field(title: lang.s("books.meta.authorSection"),
                      placeholder: lang.s("books.add.authorPlaceholder"), text: $author)
                field(title: lang.s("books.meta.categorySection"),
                      placeholder: lang.s("books.add.categoryPlaceholder"), text: $category)
                field(title: lang.s("books.meta.pagesSection"),
                      placeholder: lang.s("books.add.pagesPlaceholder"), text: $pages, numeric: true)
                field(title: lang.s("books.meta.coverSection"),
                      placeholder: lang.s("books.meta.coverPlaceholder"), text: $cover)
                SandyButton(title: lang.s("books.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    @ViewBuilder
    private func field(title: String, placeholder: String, text: Binding<String>, numeric: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            SectionHeader(title: title)
            SandyCard {
                TextField(placeholder, text: text)
                    .keyboardType(numeric ? .numberPad : .default)
                    .font(Theme.Typography.body)
            }
        }
    }

    private func save() {
        guard !submitting else { return }
        submitting = true
        // نمرّر فقط القيم اللي تغيّرت — البقية nil فما تُلمس بالباك-إند.
        let a = author.trimmingCharacters(in: .whitespaces)
        let c = category.trimmingCharacters(in: .whitespaces)
        let cov = cover.trimmingCharacters(in: .whitespaces)
        let p = Int(pages.trimmingCharacters(in: .whitespaces))
        Task {
            let ok = await onSubmit(
                a == book.author ? nil : a,
                c == book.category ? nil : c,
                (p ?? 0) == book.totalPages ? nil : p,
                cov == book.coverURL ? nil : cov)
            submitting = false
            if ok { dismiss() }
        }
    }
}


/// ورقة إضافة ملاحظة حرة على كتاب — محرّر متعدّد الأسطر.
private struct BookNoteSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    let onSubmit: (_ text: String) async -> Bool

    @State private var text = ""
    @State private var submitting = false

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        SandyPopup(title: lang.s("books.noteSheet.title")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                SectionHeader(title: lang.s("books.noteSheet.section"))
                SandyCard {
                    TextField(lang.s("books.noteSheet.placeholder"), text: $text, axis: .vertical)
                        .font(Theme.Typography.body)
                        .lineLimit(3...8)
                }
                SandyButton(title: lang.s("books.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
                .disabled(trimmed.isEmpty)
                .opacity(trimmed.isEmpty ? 0.5 : 1)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard !trimmed.isEmpty, !submitting else { return }
        submitting = true
        Task {
            let ok = await onSubmit(trimmed)
            submitting = false
            if ok { dismiss() }
        }
    }
}


/// ورقة إضافة اقتباس من كتاب — نص الاقتباس + رقم صفحة اختياري.
private struct BookQuoteSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    let onSubmit: (_ text: String, _ page: Int) async -> Bool

    @State private var text = ""
    @State private var page = ""
    @State private var submitting = false

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        SandyPopup(title: lang.s("books.quoteSheet.title")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("books.quoteSheet.textSection"))
                    SandyCard {
                        TextField(lang.s("books.quoteSheet.textPlaceholder"), text: $text, axis: .vertical)
                            .font(Theme.Typography.body)
                            .lineLimit(3...8)
                    }
                }
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("books.quoteSheet.pageSection"))
                    SandyCard {
                        TextField(lang.s("books.quoteSheet.pagePlaceholder"), text: $page)
                            .keyboardType(.numberPad)
                            .font(Theme.Typography.body)
                    }
                }
                SandyButton(title: lang.s("books.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
                .disabled(trimmed.isEmpty)
                .opacity(trimmed.isEmpty ? 0.5 : 1)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard !trimmed.isEmpty, !submitting else { return }
        submitting = true
        Task {
            let ok = await onSubmit(trimmed, Int(page.trimmingCharacters(in: .whitespaces)) ?? 0)
            submitting = false
            if ok { dismiss() }
        }
    }
}


/// ورقة هدف القراءة السنوي — عدد كتب (إلزامي للمعنى) + عدد صفحات اختياري.
private struct BookGoalSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    let goal: BookGoal
    let onSubmit: (_ booksYear: Int, _ pagesYear: Int) async -> Bool

    @State private var books: String
    @State private var pages: String
    @State private var submitting = false

    init(goal: BookGoal, onSubmit: @escaping (_ booksYear: Int, _ pagesYear: Int) async -> Bool) {
        self.goal = goal
        self.onSubmit = onSubmit
        _books = State(initialValue: goal.booksYear > 0 ? String(goal.booksYear) : "")
        _pages = State(initialValue: goal.pagesYear > 0 ? String(goal.pagesYear) : "")
    }

    private var booksValue: Int { Int(books.trimmingCharacters(in: .whitespaces)) ?? 0 }

    var body: some View {
        SandyPopup(title: lang.s("books.goalSheet.title")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("books.goalSheet.booksSection"))
                    SandyCard {
                        TextField(lang.s("books.goalSheet.booksPlaceholder"), text: $books)
                            .keyboardType(.numberPad)
                            .font(.system(size: 22, weight: .semibold, design: .rounded))
                    }
                }
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    SectionHeader(title: lang.s("books.goalSheet.pagesSection"))
                    SandyCard {
                        TextField(lang.s("books.goalSheet.pagesPlaceholder"), text: $pages)
                            .keyboardType(.numberPad)
                            .font(Theme.Typography.body)
                    }
                }
                SandyButton(title: lang.s("books.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
                .disabled(booksValue <= 0)
                .opacity(booksValue <= 0 ? 0.5 : 1)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard booksValue > 0, !submitting else { return }
        submitting = true
        Task {
            let ok = await onSubmit(booksValue, Int(pages.trimmingCharacters(in: .whitespaces)) ?? 0)
            submitting = false
            if ok { dismiss() }
        }
    }
}
