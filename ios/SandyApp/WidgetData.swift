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

    private static func reload() {
        WidgetCenter.shared.reloadAllTimelines()
    }
}
