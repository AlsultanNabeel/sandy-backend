import CoreSpotlight
import Foundation

/// مهمة/تذكير → ورقة `NotificationManager.pendingRoute`؛ عنصر قائمة تانية → حياتي؛
/// سجلّ → حياتي (`pendingTab` اللي `MainTabView` بيراقبه).
@MainActor
final class SpotlightRouter: ObservableObject {
    static let shared = SpotlightRouter()

    /// `MainTabView` بيبدّل له ويصفّره.
    @Published var pendingTab: MainTab?

    /// يرجّع false لو النشاط مش نتيجة بحث من ساندي.
    @discardableResult
    func handle(_ activity: NSUserActivity) -> Bool {
        guard activity.activityType == CSSearchableItemActionType,
              let id = activity.userInfo?[CSSearchableItemActivityIdentifier] as? String
        else { return false }
        let parts = id.split(separator: ":", maxSplits: 2, omittingEmptySubsequences: false)
        guard parts.count == 3, parts[0] == "sandy",
              let kind = SpotlightIndexer.Kind(rawValue: String(parts[1]))
        else { return false }
        switch kind {
        case .item where parts[2].hasPrefix("tasks:"):
            NotificationManager.shared.pendingRoute = .tasks
        case .item:     pendingTab = .life
        case .reminder: NotificationManager.shared.pendingRoute = .reminders
        case .entry:    pendingTab = .life
        }
        return true
    }
}
