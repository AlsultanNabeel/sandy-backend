import Foundation

// نسخ Codable خفيفة من نماذج القوائم، للكاش فقط. النماذج الأصلية مش Codable
// (بتنبني يدويًا من ردود الـAPI) وتوليد Codable تلقائيًا ممنوع بامتداد بملف تاني،
// فبدل ما نلمس النماذج نفسها — كل مرآة هون بتحوّل من/إلى نموذجها بسطرين.

/// قائمة محفوظة + علامة بيانات التجربة.
struct CachedList<M: Codable>: Codable {
    let items: [M]
    let demo: Bool
}

struct CachedTask: Codable {
    let id, text, dueAt, note, priority: String
    let done: Bool
    init(_ t: TaskItem) {
        id = t.id; text = t.text; done = t.done; dueAt = t.dueAt; note = t.note; priority = t.priority
    }
    var model: TaskItem {
        TaskItem(id: id, text: text, done: done, dueAt: dueAt, note: note, priority: priority)
    }
}

struct CachedReminder: Codable {
    let id, text, remindAt, recurrence, note: String
    let isRecurring: Bool
    init(_ r: ReminderItem) {
        id = r.id; text = r.text; remindAt = r.remindAt; isRecurring = r.isRecurring
        recurrence = r.recurrence; note = r.note
    }
    var model: ReminderItem {
        ReminderItem(id: id, text: text, remindAt: remindAt, isRecurring: isRecurring,
                     recurrence: recurrence, note: note)
    }
}

struct CachedJournalEntry: Codable {
    let id, date, text: String
    init(_ e: JournalEntry) { id = e.id; date = e.date; text = e.text }
    var model: JournalEntry { JournalEntry(id: id, date: date, text: text) }
}

struct CachedHabit: Codable {
    let id, name: String
    let streak: Int
    let doneToday: Bool
    init(_ h: HabitItem) { id = h.id; name = h.name; streak = h.streak; doneToday = h.doneToday }
    var model: HabitItem { HabitItem(id: id, name: name, streak: streak, doneToday: doneToday) }
}

struct CachedExpense: Codable {
    let id, note, category, at: String
    let amount: Double
    init(_ e: ExpenseItem) { id = e.id; amount = e.amount; note = e.note; category = e.category; at = e.at }
    var model: ExpenseItem { ExpenseItem(id: id, amount: amount, note: note, category: category, at: at) }
}

struct CachedExpenses: Codable {
    let items: [CachedExpense]
    let total: Double
    let count: Int
    let demo: Bool
}

struct CachedMemoryFact: Codable {
    let id, text, type: String
    init(_ f: MemoryFact) { id = f.id; text = f.text; type = f.type }
    var model: MemoryFact { MemoryFact(id: id, text: text, type: type) }
}

struct CachedGoal: Codable {
    let id, text, deadline, status: String
    init(_ g: GoalItem) { id = g.id; text = g.text; deadline = g.deadline; status = g.status }
    var model: GoalItem { GoalItem(id: id, text: text, deadline: deadline, status: status) }
}

struct CachedShoppingItem: Codable {
    let id, text, category, unit: String
    let done: Bool
    let price: Double
    let qty: Int
    init(_ s: ShoppingItem) {
        id = s.id; text = s.text; done = s.done; category = s.category
        price = s.price; qty = s.qty; unit = s.unit
    }
    var model: ShoppingItem {
        ShoppingItem(id: id, text: text, done: done, category: category,
                     price: price, qty: qty, unit: unit)
    }
}

struct CachedPlan: Codable {
    let id, topic, summary, finishedAt, planText: String
    init(_ p: ProjectPlan) {
        id = p.id; topic = p.topic; summary = p.summary; finishedAt = p.finishedAt; planText = p.planText
    }
    var model: ProjectPlan {
        ProjectPlan(id: id, topic: topic, summary: summary, finishedAt: finishedAt, planText: planText)
    }
}

struct CachedBook: Codable {
    let title, author, category, coverURL, status, fmt: String
    let totalPages, currentPage, rating, notesCount, quotesCount: Int
    init(_ b: BookItem) {
        title = b.title; author = b.author; category = b.category; coverURL = b.coverURL
        status = b.status; totalPages = b.totalPages; currentPage = b.currentPage
        rating = b.rating; fmt = b.fmt; notesCount = b.notesCount; quotesCount = b.quotesCount
    }
    var model: BookItem {
        BookItem(title: title, author: author, category: category, coverURL: coverURL,
                 status: status, totalPages: totalPages, currentPage: currentPage,
                 rating: rating, fmt: fmt, notesCount: notesCount, quotesCount: quotesCount)
    }
}

struct CachedBooks: Codable {
    let items: [CachedBook]
    // BookStats
    let sessions, pages, minutes, pagesPerDay, streakDays: Int
    // BookGoal
    let booksYear, pagesYear, booksDone, pagesRead: Int
    let demo: Bool

    init(items: [BookItem], stats: BookStats, goal: BookGoal, demo: Bool) {
        self.items = items.map { CachedBook($0) }
        sessions = stats.sessions; pages = stats.pages; minutes = stats.minutes
        pagesPerDay = stats.pagesPerDay; streakDays = stats.streakDays
        booksYear = goal.booksYear; pagesYear = goal.pagesYear
        booksDone = goal.booksDone; pagesRead = goal.pagesRead
        self.demo = demo
    }
    var stats: BookStats {
        BookStats(sessions: sessions, pages: pages, minutes: minutes,
                  pagesPerDay: pagesPerDay, streakDays: streakDays)
    }
    var goal: BookGoal {
        BookGoal(booksYear: booksYear, pagesYear: pagesYear, booksDone: booksDone, pagesRead: pagesRead)
    }
}
