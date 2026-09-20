import SwiftUI

@MainActor
final class BooksStore: LoadableStore {
    @Published var books: [BookItem] = []
    @Published var stats = BookStats()
    @Published var goal = BookGoal()

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let gen = beginLoad()
        let cacheKey = "books"
        if !hasSnapshot, let cached = DiskCache.load(CachedBooks.self, key: cacheKey,
                                                     userId: api.currentUserId) {
            books = cached.items.map(\.model)
            stats = cached.stats
            goal = cached.goal
            demo = cached.demo
            hasSnapshot = true
        }
        let task = Task { @MainActor in
            defer { endLoad(gen) }
            do {
                let r = try await api.booksFetch()
                guard isCurrentLoad(gen) else { return }
                withAnimation { books = r.items }
                stats = r.stats
                goal = r.goal
                demo = r.demo
                markLoaded()
                DiskCache.save(CachedBooks(items: r.items, stats: r.stats, goal: r.goal, demo: r.demo),
                               key: cacheKey, userId: api.currentUserId)
                if !r.demo { SpotlightIndexer.indexBooks(r.items) }
            } catch {
                failLoad(error, generation: gen) { notify("books.errorLoad") }
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
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("books.errorAdd")
            return false
        }
    }

    func setStatus(api: APIClient, book: BookItem, status: String) async -> Bool {
        do {
            try await api.booksSetStatus(title: book.title, status: status)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("books.errorStatus")
            return false
        }
    }

    func setMeta(api: APIClient, book: BookItem, author: String?, category: String?,
                 totalPages: Int?, coverURL: String?) async -> Bool {
        do {
            try await api.booksSetMeta(title: book.title, author: author, category: category,
                                       totalPages: totalPages, coverURL: coverURL)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("books.errorMeta")
            return false
        }
    }

    func addNote(api: APIClient, book: BookItem, text: String) async -> Bool {
        do {
            try await api.booksAddNote(title: book.title, text: text)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("books.errorNote")
            return false
        }
    }

    func addQuote(api: APIClient, book: BookItem, text: String, page: Int) async -> Bool {
        do {
            try await api.booksAddQuote(title: book.title, text: text, page: page)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("books.errorQuote")
            return false
        }
    }

    func setGoal(api: APIClient, booksYear: Int, pagesYear: Int) async -> Bool {
        do {
            try await api.booksSetGoal(booksYear: booksYear, pagesYear: pagesYear)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("books.errorGoal")
            return false
        }
    }
}
