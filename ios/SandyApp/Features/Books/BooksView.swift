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
        // الخلفية موحّدة على مستوى MainTabView — لا نكرّرها هون (طبقة مهدورة).
        ZStack {
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
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            HStack(spacing: Theme.Spacing.xs) {
                Image(systemName: "chart.bar.fill")
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.accent)
                Text(lang.s("books.stats.title"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                Spacer(minLength: 0)
                if store.stats.streakDays > 0 {
                    Text(String(format: lang.s("books.stats.streakDays"), "\(store.stats.streakDays)"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.accentDeep)
                }
            }
            HStack(spacing: Theme.Spacing.lg) {
                statPill(value: store.stats.sessions, label: lang.s("books.stats.sessions"))
                statPill(value: store.stats.pages, label: lang.s("books.stats.pages"))
                statPill(value: store.stats.minutes, label: lang.s("books.stats.minutes"))
            }
        }
        .sandyCard(.primary)
        .sandyGlow()
    }

    private func statPill(value: Int, label: String) -> some View {
        VStack(spacing: Theme.Spacing.xs) {
            Text("\(value)")
                .font(Theme.Typography.title)
                .foregroundColor(Theme.Colors.accent)
                .monospacedDigit()
            Text(label)
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.tertiaryText)
        }
        .frame(maxWidth: .infinity)
    }

    private var goalCard: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            HStack(spacing: Theme.Spacing.xs) {
                Image(systemName: "target")
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondary)
                Text(lang.s("books.goal.title"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                Spacer(minLength: 0)
                if !store.demo {
                    Button {
                        store.notice = ""
                        showGoal = true
                    } label: {
                        Text(lang.s(store.goal.hasTarget ? "books.goal.edit" : "books.goal.set"))
                            .font(Theme.Typography.caption)
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
        .sandyCard(.info)
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
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                        .fixedSize(horizontal: false, vertical: true)
                    if !book.author.isEmpty {
                        Text(String(format: lang.s("books.card.by"), book.author))
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                    if book.totalPages > 0 {
                        Text(String(format: lang.s("books.card.progress"),
                                    "\(book.currentPage)", "\(book.totalPages)"))
                            .font(Theme.Typography.caption)
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
                .font(.system(size: Theme.Icon.xl))
                .foregroundColor(Theme.Colors.secondaryText)
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


// MARK: - حالات الكتاب


// MARK: - شيت إضافة كتاب


// MARK: - شيت تغيير الحالة


// MARK: - شيت تعديل التفاصيل (الميتاداتا)


// MARK: - شيت إضافة ملاحظة


// MARK: - شيت إضافة اقتباس


// MARK: - شيت الهدف السنوي


// MARK: - الستور


// MARK: - النماذج (تطابق JSON الباك-إند بالضبط)





// MARK: - نداءات الباك-إند (نمدّد APIClient هون بلا ما نلمس ملفه)
