import CoreSpotlight
import Foundation

/// يفتح التطبيق على المكان الصح لمّا المستخدم ينقر نتيجة ساندي ببحث النظام.
///
/// • مهمة / تذكير → نفس ورقة الإشعار (`NotificationManager.pendingRoute`) —
///   `MainTabView` بيعرضها أصلًا، فما بدها ربط إضافي.
/// • كتاب → تبويب ساندي (فيه رف الكتب) عبر `DeepLinkRouter` (.chat).
/// • خاطرة → تبويب «حياتي»، ذاكرة → الرئيسية (منها الملف الشخصي) عبر `pendingTab`
///   هون — `MainTabView` لازم يراقبه (راجع التقرير لسطور الربط).
@MainActor
final class SpotlightRouter: ObservableObject {
    static let shared = SpotlightRouter()

    /// تبويب مطلوب من نتيجة بحث — `MainTabView` بيبدّل له ويصفّره.
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
        case .task:     NotificationManager.shared.pendingRoute = .tasks
        case .reminder: NotificationManager.shared.pendingRoute = .reminders
        case .book:     DeepLinkRouter.shared.pending = .chat
        case .journal:  pendingTab = .life
        case .memory:   pendingTab = .home
        }
        return true
    }
}
