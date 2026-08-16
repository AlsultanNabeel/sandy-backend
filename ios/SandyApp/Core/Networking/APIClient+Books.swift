import SwiftUI

extension APIClient {
    /// All fields optional so a missing key (e.g. the guest payload omits `goal`)
    /// decodes to nil and falls back to the same defaults the old dictionary reads used.
    private struct BooksResponse: Decodable {
        let items: [Row]?
        let stats: Stats?
        let goal: Goal?
        let demo: Bool?
        struct Row: Decodable {
            let title: String?
            let author: String?
            let category: String?
            let cover_url: String?
            let status: String?
            let total_pages: Int?
            let current_page: Int?
            let rating: Int?
            let fmt: String?
            let notes_count: Int?
            let quotes_count: Int?
        }
        struct Stats: Decodable {
            let sessions: Int?
            let pages: Int?
            let minutes: Int?
            let pages_per_day: Int?
            let streak_days: Int?
        }
        struct Goal: Decodable {
            let books_year: Int?
            let pages_year: Int?
            let books_done: Int?
            let pages_read: Int?
        }
    }

    /// GET /api/life/books → {"items":[…], "stats":{…}, "goal":{…}, "demo":bool}
    func booksFetch() async throws -> BooksResult {
        let r: BooksResponse = try await fetch("/api/life/books")
        let items = (r.items ?? []).compactMap { row -> BookItem? in
            guard let title = row.title, !title.isEmpty else { return nil }
            return BookItem(
                title: title,
                author: row.author ?? "",
                category: row.category ?? "",
                coverURL: row.cover_url ?? "",
                status: row.status ?? "reading",
                totalPages: row.total_pages ?? 0,
                currentPage: row.current_page ?? 0,
                rating: row.rating ?? 0,
                fmt: row.fmt ?? "",
                notesCount: row.notes_count ?? 0,
                quotesCount: row.quotes_count ?? 0)
        }
        let s = r.stats
        let stats = BookStats(
            sessions: s?.sessions ?? 0,
            pages: s?.pages ?? 0,
            minutes: s?.minutes ?? 0,
            pagesPerDay: s?.pages_per_day ?? 0,
            streakDays: s?.streak_days ?? 0)
        let g = r.goal
        let goal = BookGoal(
            booksYear: g?.books_year ?? 0,
            pagesYear: g?.pages_year ?? 0,
            booksDone: g?.books_done ?? 0,
            pagesRead: g?.pages_read ?? 0)
        return BooksResult(items: items, stats: stats, goal: goal, demo: r.demo ?? false)
    }

    /// Optional fields omit themselves when nil (encodeIfPresent), matching the
    /// old "only send non-empty keys" dictionary build.
    private struct BookAdd: Encodable {
        let title: String
        let status: String
        let total_pages: Int?
        let author: String?
        let category: String?
    }

    /// POST /api/life/books {title,status,total_pages,author,category} → {"ok":bool}
    func booksAdd(title: String, status: String, author: String,
                  category: String, totalPages: Int) async throws {
        try await send("/api/life/books", method: "POST",
                       body: BookAdd(title: title, status: status,
                                     total_pages: totalPages > 0 ? totalPages : nil,
                                     author: author.isEmpty ? nil : author,
                                     category: category.isEmpty ? nil : category))
    }

    private struct BookStatusBody: Encodable {
        let title: String
        let status: String
    }

    /// POST /api/life/books/status {title,status} → {"ok":bool}
    func booksSetStatus(title: String, status: String) async throws {
        try await send("/api/life/books/status", method: "POST",
                       body: BookStatusBody(title: title, status: status))
    }

    private struct BookMeta: Encodable {
        let title: String
        let author: String?
        let category: String?
        let total_pages: Int?
        let cover_url: String?
    }

    /// POST /api/life/books/meta {title, author?,category?,total_pages?,cover_url?} → {"ok":bool}
    /// الباك-إند يعتبر الحقل الغائب = بلا تغيير — القيم nil تُحذف من الـJSON.
    func booksSetMeta(title: String, author: String?, category: String?,
                      totalPages: Int?, coverURL: String?) async throws {
        guard author != nil || category != nil || totalPages != nil || coverURL != nil else { return }
        try await send("/api/life/books/meta", method: "POST",
                       body: BookMeta(title: title, author: author, category: category,
                                      total_pages: totalPages, cover_url: coverURL))
    }

    private struct BookNote: Encodable {
        let title: String
        let text: String
    }

    /// POST /api/life/books/note {title,text} → {"ok":bool}
    func booksAddNote(title: String, text: String) async throws {
        try await send("/api/life/books/note", method: "POST",
                       body: BookNote(title: title, text: text))
    }

    private struct BookQuote: Encodable {
        let title: String
        let text: String
        let page: Int
    }

    /// POST /api/life/books/quote {title,text,page} → {"ok":bool}
    func booksAddQuote(title: String, text: String, page: Int) async throws {
        try await send("/api/life/books/quote", method: "POST",
                       body: BookQuote(title: title, text: text, page: page))
    }

    private struct BookGoalBody: Encodable {
        let books_year: Int
        let pages_year: Int
    }

    /// POST /api/life/books/goal {books_year,pages_year} → {"ok":bool}
    func booksSetGoal(booksYear: Int, pagesYear: Int) async throws {
        try await send("/api/life/books/goal", method: "POST",
                       body: BookGoalBody(books_year: booksYear, pages_year: pagesYear))
    }
}
