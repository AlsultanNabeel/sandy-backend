import SwiftUI

// ─────────────────────────────────────────────────────────────────────────
//  Weekly insights — model, API call and store for /api/insights/weekly.
//  The server compares the last 7 days with the 7 before them and adds one
//  warm sentence from Sandy (cached per week on the server).
// ─────────────────────────────────────────────────────────────────────────

/// One number on the summary: this week vs last week.
struct InsightMetric: Identifiable, Decodable, Equatable {
    let key: String
    let current: Double
    let previous: Double
    var id: String { key }

    /// Relative change, or nil when last week was zero (nothing to compare with).
    var change: Double? {
        previous == 0 ? nil : (current - previous) / previous
    }
}

struct WeeklyInsights: Decodable, Equatable {
    let demo: Bool?
    let week: String?
    let metrics: [InsightMetric]?
    let bestStreak: Int?
    let sentence: String?

    enum CodingKeys: String, CodingKey {
        case demo, week, metrics, sentence
        case bestStreak = "best_streak"
    }
}

extension APIClient {
    /// The weekly summary in the app's language (Sandy's sentence follows it).
    func getWeeklyInsights() async throws -> WeeklyInsights {
        let lang = AppLocale.lang.rawValue
        return try await fetch("/api/insights/weekly?lang=\(lang)", timeout: 20)
    }
}

@MainActor
final class InsightsStore: LoadableStore {
    @Published var insights: WeeklyInsights?

    private var loadTask: Task<Void, Never>?

    /// Store-owned load (survives the view's task being cancelled by a gesture).
    func load(api: APIClient) async {
        loadTask?.cancel()
        let gen = beginLoad()
        let task = Task { @MainActor in
            defer { endLoad(gen) }
            do {
                let r = try await api.getWeeklyInsights()
                guard isCurrentLoad(gen) else { return }
                insights = r
                demo = r.demo ?? false
                clearNotice()
            } catch {
                if !error.isCancellation, isCurrentLoad(gen) { notify("insights.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    var metrics: [InsightMetric] { insights?.metrics ?? [] }
}
