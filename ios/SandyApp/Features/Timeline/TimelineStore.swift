import SwiftUI

@MainActor
final class TimelineStore: LoadableStore {
    @Published var events: [TimelineEvent] = []

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                events = try await api.getTimeline()
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("timeline.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// حذف متفائل فوري من الخط، ثم حذف المصدر حسب النوع؛ يرجع العنصر عند الفشل.
    func delete(api: APIClient, event: TimelineEvent) {
        guard let idx = events.firstIndex(where: { $0.id == event.id }) else { return }
        events.remove(at: idx)
        Task { @MainActor in
            do {
                switch event.type {
                case "task":     try await api.deleteTask(id: event.id)
                case "reminder": try await api.deleteReminder(id: event.id)
                case "expense":  try await api.deleteExpense(id: event.id)
                case "journal":  try await api.deleteJournalEntry(id: event.id)
                default: break
                }
            } catch {
                events.insert(event, at: min(idx, events.count))
                notice = LanguageManager.shared.s("timeline.errorDelete")
            }
        }
    }

    /// تعليم منجز/غير منجز لمهمة من الخط (تحديث متفائل) — أداة سريعة حسب النوع.
    func toggleTask(api: APIClient, event: TimelineEvent) {
        guard event.type == "task",
              let idx = events.firstIndex(where: { $0.id == event.id }) else { return }
        let target = !event.done
        events[idx].done = target
        Task { @MainActor in
            do {
                try await api.setTaskDone(id: event.id, done: target)
            } catch {
                if let i = events.firstIndex(where: { $0.id == event.id }) { events[i].done = !target }
                notice = LanguageManager.shared.s("timeline.errorToggle")
            }
        }
    }

    /// الأحداث مجمّعة زمنيًا (اليوم/أمس/الأسبوع/أقدم)، فاضي تُحذف، والترتيب محفوظ.
    var grouped: [(String, [TimelineEvent])] {
        let order = ["today", "yesterday", "week", "older"]
        var map: [String: [TimelineEvent]] = [:]
        for e in events { map[bucket(e.ts), default: []].append(e) }
        return order.compactMap { key in
            guard let evs = map[key], !evs.isEmpty else { return nil }
            return (key, evs)
        }
    }

    private func bucket(_ iso: String) -> String {
        guard let d = parseISO(iso) else { return "older" }
        let cal = Calendar.current
        if cal.isDateInToday(d) { return "today" }
        if cal.isDateInYesterday(d) { return "yesterday" }
        if let days = cal.dateComponents([.day], from: d, to: Date()).day, days < 7 { return "week" }
        return "older"
    }

    private func parseISO(_ iso: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: iso) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: iso)
    }
}
