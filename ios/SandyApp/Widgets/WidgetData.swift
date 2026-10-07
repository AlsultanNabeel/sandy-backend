import Foundation
import WidgetKit

// لقطة صغيرة بمجموعة التطبيقات للويدجت، فما بيحتاج شبكة ولا توكن.
enum WidgetData {
    static let suiteName = "group.com.sandy.app"

    private static var store: UserDefaults? { UserDefaults(suiteName: suiteName) }

    enum Key {
        static let activeTasks = "active_tasks"
        static let lang = "app_lang"  // "ar" | "en"
        /// لازم يضل مطابق لـ ios/SandyWidget/SandyTasksWidget.swift.
        static let openTasks = "open_tasks"
    }

    static func setUpcomingReminders(_ upcoming: UpcomingReminders) {
        store?.set(try? JSONEncoder().encode(upcoming), forKey: UpcomingReminders.key)
        reload()
    }

    static func setActiveTasks(count: Int) {
        store?.set(count, forKey: Key.activeTasks)
        reload()
    }

    /// ما بتعمل reload لحالها — `setActiveTasks` اللي بعدها بتعمله.
    static func setOpenTasks(_ tasks: [TaskItem]) {
        let rows: [[String: String]] = tasks.prefix(10).map {
            ["id": $0.id, "text": $0.text, "priority": $0.priority]
        }
        if let data = try? JSONSerialization.data(withJSONObject: rows) {
            store?.set(data, forKey: Key.openTasks)
        }
    }

    static func syncLanguage() {
        reload()
    }

    /// The widget keeps drawing the previous account's data after sign-out, so wipe it.
    /// Clears its own keys, not the whole suite (shared with `SharedAuth`).
    static func clearAll() {
        guard let store else { return }
        for key in [UpcomingReminders.key, Key.activeTasks, Key.openTasks] {
            store.removeObject(forKey: key)
        }
        WidgetCenter.shared.reloadAllTimelines()
    }

    private static func reload() {
        store?.set(AppLocale.lang.rawValue, forKey: Key.lang)
        WidgetCenter.shared.reloadAllTimelines()
    }
}
