import Foundation
import WidgetKit

// ─────────────────────────────────────────────────────────────────────────
//  WidgetData — جسر بيانات التطبيق ← الويدجت عبر مجموعة التطبيقات المشتركة.
//
//  التطبيق يكتب لقطة صغيرة (التذكير الجاي + عدد المهام النشطة) بمساحة مشتركة
//  (App Group)، والويدجت يقراها. هيك ما نحتاج شبكة ولا توكن بالويدجت. كل كتابة
//  تطلب من النظام يعيد بناء الويدجت فورًا.
// ─────────────────────────────────────────────────────────────────────────
enum WidgetData {
    static let suiteName = "group.com.sandy.app"

    private static var store: UserDefaults? { UserDefaults(suiteName: suiteName) }

    enum Key {
        static let reminderText = "next_reminder_text"
        static let reminderAt = "next_reminder_at"   // timeIntervalSince1970
        static let activeTasks = "active_tasks"
        static let lang = "app_lang"                  // "ar" | "en" — لغة التطبيق للويدجت
        /// JSON: [{id, text, priority}] — أوّل المهام المفتوحة لويدجت المهام التفاعلي.
        /// لازم يضل مطابق لـ ios/SandyWidget/SandyTasksWidget.swift.
        static let openTasks = "open_tasks"
    }

    /// أقرب تذكير قادم (أو nil لو ما في).
    static func setNextReminder(text: String?, date: Date?) {
        store?.set(text, forKey: Key.reminderText)
        store?.set(date?.timeIntervalSince1970 ?? 0, forKey: Key.reminderAt)
        reload()
    }

    /// عدد المهام النشطة (غير المنجزة).
    static func setActiveTasks(count: Int) {
        store?.set(count, forKey: Key.activeTasks)
        reload()
    }

    /// أوّل المهام المفتوحة لويدجت المهام (زر ✓ بيكمّلها من الويدجت نفسه).
    /// ما بتعمل reload لحالها — `setActiveTasks` اللي بعدها بتعمله.
    /// التوكن والعنوان للنيّة بالويدجت بيكتبهم `SharedAuth` من `APIClient`.
    static func setOpenTasks(_ tasks: [TaskItem]) {
        let rows: [[String: String]] = tasks.prefix(10).map {
            ["id": $0.id, "text": $0.text, "priority": $0.priority]
        }
        if let data = try? JSONSerialization.data(withJSONObject: rows) {
            store?.set(data, forKey: Key.openTasks)
        }
    }

    /// لغة التطبيق تغيّرت — الويدجت يعيد رسم نصوصه وأرقامه ووقته بلغتها.
    static func syncLanguage() {
        reload()
    }

    private static func reload() {
        // كل تحديث بيحمل لغة التطبيق معه، حتى يعرض الويدجت بنفس لغة التطبيق.
        store?.set(AppLocale.lang.rawValue, forKey: Key.lang)
        WidgetCenter.shared.reloadAllTimelines()
    }
}
