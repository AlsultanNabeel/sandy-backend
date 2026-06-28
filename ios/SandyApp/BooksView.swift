import SwiftUI

/// رفّ القراءة — يعرض كتب المستخدم مع إحصائيات آخر ٣٠ يوم وهدف السنة، عبر
/// `/api/life/books`. كل عملية تعديل بالباك-إند مفتاحها عنوان الكتاب (title)، مش
/// معرّفه — فبنمرّر العنوان بكل النداءات. نمط الستور المعتمد: الجلب بمهمة يملكها
/// الستور (محصّنة ضد إلغاء الإيماءات). يحاكي MemoryView/LifeView للستور/الـ CRUD/
/// الشيتات/السحب. ما في نقطة نهاية حذف كتاب بالباك-إند، فالتفاعلات = تغيير الحالة
/// والتعديل وإضافة ملاحظة/اقتباس (لا حذف مدمّر).
struct BooksView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = BooksStore()
    @State private var showAdd = false
    /// الورقة النشطة لكتاب معيّن (تغيير حالة / تعديل / ملاحظة / اقتباس).
    @State private var activeSheet: BookSheet?
    /// هل ورقة الهدف السنوي مفتوحة.
    @State private var showGoal = false

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if store.demo { DemoBanner() }

                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                content
            }
        }
        .navigationTitle(lang.s("books.title"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                SandyButton(title: lang.s("books.add"),
                            systemImage: "plus.circle.fill",
                            style: .secondary) {
                    store.notice = ""
                    showAdd = true
                }
                .disabled(store.demo)
                .opacity(store.demo ? 0.5 : 1)
            }
        }
        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.books.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .fullScreenCover(isPresented: $showAdd) {
            BookAddSheet { title, status, author, category, pages in
                await store.add(api: state.api, title: title, status: status,
                                author: author, category: category, totalPages: pages)
            }
        }
        .fullScreenCover(isPresented: $showGoal) {
            BookGoalSheet(goal: store.goal) { booksYear, pagesYear in
                await store.setGoal(api: state.api, booksYear: booksYear, pagesYear: pagesYear)
            }
        }
        .fullScreenCover(item: $activeSheet) { sheet in
            sheetView(for: sheet)
        }
    }

    // ── الورقة حسب نوعها ─────────────────────────────────────────────────

    @ViewBuilder
    private func sheetView(for sheet: BookSheet) -> some View {
        switch sheet.kind {
        case .status:
            BookStatusSheet(current: sheet.book.status) { status in
                await store.setStatus(api: state.api, book: sheet.book, status: status)
            }
        case .meta:
            BookMetaSheet(book: sheet.book) { author, category, pages, cover in
                await store.setMeta(api: state.api, book: sheet.book,
                                    author: author, category: category,
                                    totalPages: pages, coverURL: cover)
            }
        case .note:
            BookNoteSheet { text in
                await store.addNote(api: state.api, book: sheet.book, text: text)
            }
        case .quote:
            BookQuoteSheet { text, page in
                await store.addQuote(api: state.api, book: sheet.book, text: text, page: page)
            }
        }
    }

    // ── المحتوى ──────────────────────────────────────────────────────────

    @ViewBuilder
    private var content: some View {
        if store.books.isEmpty && !store.loading {
            emptyView
        } else {
            List {
                header
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: Theme.Spacing.sm, leading: Theme.Spacing.md,
                                              bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                ForEach(BookStatus.allCases) { status in
                    let group = store.books.filter { $0.status == status.rawValue }
                    if !group.isEmpty {
                        Section {
                            ForEach(group) { book in
                                bookRow(book)
                                    .listRowBackground(Color.clear)
                                    .listRowSeparator(.hidden)
                                    .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                              bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                                    .swipeActions(edge: .trailing) {
                                        if !store.demo {
                                            Button { open(.note, book) } label: {
                                                Label(lang.s("books.card.addNote"), systemImage: "note.text")
                                            }
                                            .tint(Theme.Colors.warn)
                                            Button { open(.quote, book) } label: {
                                                Label(lang.s("books.card.addQuote"), systemImage: "quote.bubble")
                                            }
                                            .tint(Theme.Colors.success)
                                        }
                                    }
                                    .swipeActions(edge: .leading) {
                                        if !store.demo {
                                            Button { open(.status, book) } label: {
                                                Label(lang.s("books.card.changeStatus"), systemImage: "arrow.left.arrow.right")
                                            }
                                            .tint(Theme.Colors.accent)
                                        }
                                    }
                            }
                        } header: {
                            Text(lang.s(status.sectionKey))
                                .font(Theme.Typography.callout)
                                .foregroundColor(Theme.Colors.secondaryText)
                        }
                        .listRowBackground(Color.clear)
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.books.count)
        }
    }

    /// ترويسة القائمة: بطاقة إحصائيات آخر ٣٠ يوم + بطاقة هدف السنة.
    private var header: some View {
        VStack(spacing: Theme.Spacing.md) {
            statsCard
            goalCard
        }
    }

    private var statsCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                HStack(spacing: Theme.Spacing.xs) {
                    Image(systemName: "chart.bar.fill")
                        .font(.caption)
                        .foregroundColor(Theme.Colors.accent)
                    Text(lang.s("books.stats.title"))
                        .font(.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                    Spacer(minLength: 0)
                    if store.stats.streakDays > 0 {
                        Text(String(format: lang.s("books.stats.streakDays"), "\(store.stats.streakDays)"))
                            .font(.caption2)
                            .foregroundColor(Theme.Colors.accentDeep)
                    }
                }
                HStack(spacing: Theme.Spacing.lg) {
                    statPill(value: store.stats.sessions, label: lang.s("books.stats.sessions"))
                    statPill(value: store.stats.pages, label: lang.s("books.stats.pages"))
                    statPill(value: store.stats.minutes, label: lang.s("books.stats.minutes"))
                }
            }
        }
    }

    private func statPill(value: Int, label: String) -> some View {
        VStack(spacing: 2) {
            Text("\(value)")
                .font(.system(size: 22, weight: .bold, design: .rounded))
                .foregroundColor(Theme.Colors.accent)
                .monospacedDigit()
            Text(label)
                .font(.caption2)
                .foregroundColor(Theme.Colors.secondaryText)
        }
        .frame(maxWidth: .infinity)
    }

    private var goalCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                HStack(spacing: Theme.Spacing.xs) {
                    Image(systemName: "target")
                        .font(.caption)
                        .foregroundColor(Theme.Colors.accent)
                    Text(lang.s("books.goal.title"))
                        .font(.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                    Spacer(minLength: 0)
                    if !store.demo {
                        Button {
                            store.notice = ""
                            showGoal = true
                        } label: {
                            Text(lang.s(store.goal.hasTarget ? "books.goal.edit" : "books.goal.set"))
                                .font(.caption)
                                .foregroundColor(Theme.Colors.accentDeep)
                        }
                        .buttonStyle(.plain)
                    }
                }
                if store.goal.hasTarget {
                    if store.goal.booksYear > 0 {
                        goalLine(format: lang.s("books.goal.books"),
                                 done: store.goal.booksDone, target: store.goal.booksYear)
                    }
                    if store.goal.pagesYear > 0 {
                        goalLine(format: lang.s("books.goal.pages"),
                                 done: store.goal.pagesRead, target: store.goal.pagesYear)
                    }
                } else {
                    Text(lang.s("books.goal.none"))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func goalLine(format: String, done: Int, target: Int) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            Text(String(format: format, "\(done)", "\(target)"))
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.primaryText)
            ProgressView(value: Double(min(done, target)), total: Double(max(target, 1)))
                .tint(Theme.Colors.accent)
        }
    }

    private func bookRow(_ book: BookItem) -> some View {
        SandyCard {
            HStack(alignment: .top, spacing: Theme.Spacing.md) {
                cover(book)
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(book.title)
                        .font(.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                        .fixedSize(horizontal: false, vertical: true)
                    if !book.author.isEmpty {
                        Text(String(format: lang.s("books.card.by"), book.author))
                            .font(.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                    if book.totalPages > 0 {
                        Text(String(format: lang.s("books.card.progress"),
                                    "\(book.currentPage)", "\(book.totalPages)"))
                            .font(.caption)
                            .foregroundColor(Theme.Colors.accentDeep)
                        ProgressView(value: Double(min(book.currentPage, book.totalPages)),
                                     total: Double(max(book.totalPages, 1)))
                            .tint(Theme.Colors.accent)
                    }
                    if book.rating > 0 {
                        stars(book.rating)
                    }
                    if book.notesCount > 0 || book.quotesCount > 0 {
                        HStack(spacing: Theme.Spacing.md) {
                            if book.notesCount > 0 {
                                metaBadge(icon: "note.text",
                                          text: String(format: lang.s("books.card.notes"), "\(book.notesCount)"))
                            }
                            if book.quotesCount > 0 {
                                metaBadge(icon: "quote.bubble",
                                          text: String(format: lang.s("books.card.quotes"), "\(book.quotesCount)"))
                            }
                        }
                    }
                }
                Spacer(minLength: 0)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { if !store.demo { open(.status, book) } }
        .contextMenu {
            if !store.demo {
                Button { open(.status, book) } label: {
                    Label(lang.s("books.card.changeStatus"), systemImage: "arrow.left.arrow.right")
                }
                Button { open(.meta, book) } label: {
                    Label(lang.s("books.card.edit"), systemImage: "pencil")
                }
                Button { open(.note, book) } label: {
                    Label(lang.s("books.card.addNote"), systemImage: "note.text")
                }
                Button { open(.quote, book) } label: {
                    Label(lang.s("books.card.addQuote"), systemImage: "quote.bubble")
                }
            }
        }
    }

    /// غلاف صغير: صورة من رابط إن وُجد، وإلا أيقونة كتاب لطيفة.
    @ViewBuilder
    private func cover(_ book: BookItem) -> some View {
        let shape = RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
        Group {
            if let url = book.coverURL.isEmpty ? nil : URL(string: book.coverURL) {
                AsyncImage(url: url) { image in
                    image.resizable().scaledToFill()
                } placeholder: {
                    coverFallback
                }
            } else {
                coverFallback
            }
        }
        .frame(width: 46, height: 64)
        .clipShape(shape)
        .overlay(shape.stroke(Theme.Colors.border, lineWidth: 1))
    }

    private var coverFallback: some View {
        ZStack {
            Theme.Colors.accent.opacity(0.12)
            Image(systemName: "book.closed.fill")
                .foregroundColor(Theme.Colors.accent.opacity(0.7))
        }
    }

    private func metaBadge(icon: String, text: String) -> some View {
        HStack(spacing: 3) {
            Image(systemName: icon)
                .font(.caption2)
            Text(text)
                .font(.caption2)
        }
        .foregroundColor(Theme.Colors.secondaryText)
    }

    private func stars(_ rating: Int) -> some View {
        HStack(spacing: 2) {
            ForEach(0..<5, id: \.self) { i in
                Image(systemName: i < rating ? "star.fill" : "star")
                    .font(.caption2)
                    .foregroundColor(i < rating ? Theme.Colors.warn : Theme.Colors.secondaryText)
            }
        }
    }

    private var emptyView: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "books.vertical.fill")
                .font(.system(size: 44))
                .foregroundColor(Theme.Colors.accent.opacity(0.5))
            Text(lang.s("books.empty"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
            SandyButton(title: lang.s("books.add"),
                        systemImage: "plus.circle.fill") {
                store.notice = ""
                showAdd = true
            }
            .disabled(store.demo)
            .opacity(store.demo ? 0.5 : 1)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Theme.Spacing.lg)
    }

    private func open(_ kind: BookSheet.Kind, _ book: BookItem) {
        store.notice = ""
        activeSheet = BookSheet(kind: kind, book: book)
    }
}

// MARK: - أنواع الورقة لكتاب معيّن

/// تعريف لأي ورقة تخصّ كتابًا محدّدًا (لتمريرها لـ `.fullScreenCover(item:)`).
private struct BookSheet: Identifiable {
    enum Kind { case status, meta, note, quote }
    let id = UUID()
    let kind: Kind
    let book: BookItem
}

// MARK: - حالات الكتاب

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

// MARK: - شيت إضافة كتاب

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

// MARK: - شيت تغيير الحالة

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

// MARK: - شيت تعديل التفاصيل (الميتاداتا)

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

// MARK: - شيت إضافة ملاحظة

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

// MARK: - شيت إضافة اقتباس

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

// MARK: - شيت الهدف السنوي

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

// MARK: - الستور

@MainActor
final class BooksStore: ObservableObject {
    @Published var books: [BookItem] = []
    @Published var stats = BookStats()
    @Published var goal = BookGoal()
    @Published var loading = false
    @Published var demo = false
    @Published var notice = ""

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                let r = try await api.booksFetch()
                withAnimation { books = r.items }
                stats = r.stats
                goal = r.goal
                demo = r.demo
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("books.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة كتاب ثم إعادة جلب. يرجّع نجاح/فشل ليتقرّر إغلاق الورقة.
    func add(api: APIClient, title: String, status: String,
             author: String, category: String, totalPages: Int) async -> Bool {
        do {
            try await api.booksAdd(title: title, status: status, author: author,
                                   category: category, totalPages: totalPages)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("books.errorAdd")
            return false
        }
    }

    func setStatus(api: APIClient, book: BookItem, status: String) async -> Bool {
        do {
            try await api.booksSetStatus(title: book.title, status: status)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("books.errorStatus")
            return false
        }
    }

    func setMeta(api: APIClient, book: BookItem, author: String?, category: String?,
                 totalPages: Int?, coverURL: String?) async -> Bool {
        do {
            try await api.booksSetMeta(title: book.title, author: author, category: category,
                                       totalPages: totalPages, coverURL: coverURL)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("books.errorMeta")
            return false
        }
    }

    func addNote(api: APIClient, book: BookItem, text: String) async -> Bool {
        do {
            try await api.booksAddNote(title: book.title, text: text)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("books.errorNote")
            return false
        }
    }

    func addQuote(api: APIClient, book: BookItem, text: String, page: Int) async -> Bool {
        do {
            try await api.booksAddQuote(title: book.title, text: text, page: page)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("books.errorQuote")
            return false
        }
    }

    func setGoal(api: APIClient, booksYear: Int, pagesYear: Int) async -> Bool {
        do {
            try await api.booksSetGoal(booksYear: booksYear, pagesYear: pagesYear)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("books.errorGoal")
            return false
        }
    }
}

// MARK: - النماذج (تطابق JSON الباك-إند بالضبط)

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

// MARK: - نداءات الباك-إند (نمدّد APIClient هون بلا ما نلمس ملفه)

extension APIClient {
    /// GET /api/life/books → {"items":[…], "stats":{…}, "goal":{…}, "demo":bool}
    /// ملاحظة: الزائر يرجّع stats مبسّطة وبدون goal — نقرأ كل شي بحذر مع قيم افتراضية.
    func booksFetch() async throws -> BooksResult {
        let r = try await request("/api/life/books")
        let items = (r["items"] as? [[String: Any]] ?? []).compactMap { row -> BookItem? in
            guard let title = row["title"] as? String, !title.isEmpty else { return nil }
            return BookItem(
                title: title,
                author: row["author"] as? String ?? "",
                category: row["category"] as? String ?? "",
                coverURL: row["cover_url"] as? String ?? "",
                status: row["status"] as? String ?? "reading",
                totalPages: (row["total_pages"] as? NSNumber)?.intValue ?? 0,
                currentPage: (row["current_page"] as? NSNumber)?.intValue ?? 0,
                rating: (row["rating"] as? NSNumber)?.intValue ?? 0,
                fmt: row["fmt"] as? String ?? "",
                notesCount: (row["notes_count"] as? NSNumber)?.intValue ?? 0,
                quotesCount: (row["quotes_count"] as? NSNumber)?.intValue ?? 0)
        }
        let s = r["stats"] as? [String: Any] ?? [:]
        let stats = BookStats(
            sessions: (s["sessions"] as? NSNumber)?.intValue ?? 0,
            pages: (s["pages"] as? NSNumber)?.intValue ?? 0,
            minutes: (s["minutes"] as? NSNumber)?.intValue ?? 0,
            pagesPerDay: (s["pages_per_day"] as? NSNumber)?.intValue ?? 0,
            streakDays: (s["streak_days"] as? NSNumber)?.intValue ?? 0)
        let g = r["goal"] as? [String: Any] ?? [:]
        let goal = BookGoal(
            booksYear: (g["books_year"] as? NSNumber)?.intValue ?? 0,
            pagesYear: (g["pages_year"] as? NSNumber)?.intValue ?? 0,
            booksDone: (g["books_done"] as? NSNumber)?.intValue ?? 0,
            pagesRead: (g["pages_read"] as? NSNumber)?.intValue ?? 0)
        return BooksResult(items: items, stats: stats, goal: goal,
                           demo: r["demo"] as? Bool ?? false)
    }

    /// POST /api/life/books {title,status,total_pages,author,category} → {"ok":bool}
    func booksAdd(title: String, status: String, author: String,
                  category: String, totalPages: Int) async throws {
        var body: [String: Any] = ["title": title, "status": status]
        if totalPages > 0 { body["total_pages"] = totalPages }
        if !author.isEmpty { body["author"] = author }
        if !category.isEmpty { body["category"] = category }
        _ = try await request("/api/life/books", method: "POST", body: body)
    }

    /// POST /api/life/books/status {title,status} → {"ok":bool}
    func booksSetStatus(title: String, status: String) async throws {
        _ = try await request("/api/life/books/status", method: "POST",
                              body: ["title": title, "status": status])
    }

    /// POST /api/life/books/meta {title, author?,category?,total_pages?,cover_url?} → {"ok":bool}
    /// الباك-إند يعتبر الحقل الغائب أو الفاضي = بلا تغيير — نمرّر فقط القيم غير nil.
    /// (الغلاف يُحدَّث عبر meta بمفتاح cover_url — مدعوم بمسار set_book_cover.)
    func booksSetMeta(title: String, author: String?, category: String?,
                      totalPages: Int?, coverURL: String?) async throws {
        var body: [String: Any] = ["title": title]
        if let author { body["author"] = author }
        if let category { body["category"] = category }
        if let totalPages { body["total_pages"] = totalPages }
        if let coverURL { body["cover_url"] = coverURL }
        guard body.count > 1 else { return }
        _ = try await request("/api/life/books/meta", method: "POST", body: body)
    }

    /// POST /api/life/books/note {title,text} → {"ok":bool}
    func booksAddNote(title: String, text: String) async throws {
        _ = try await request("/api/life/books/note", method: "POST",
                              body: ["title": title, "text": text])
    }

    /// POST /api/life/books/quote {title,text,page} → {"ok":bool}
    func booksAddQuote(title: String, text: String, page: Int) async throws {
        _ = try await request("/api/life/books/quote", method: "POST",
                              body: ["title": title, "text": text, "page": page])
    }

    /// POST /api/life/books/goal {books_year,pages_year} → {"ok":bool}
    func booksSetGoal(booksYear: Int, pagesYear: Int) async throws {
        _ = try await request("/api/life/books/goal", method: "POST",
                              body: ["books_year": booksYear, "pages_year": pagesYear])
    }
}
