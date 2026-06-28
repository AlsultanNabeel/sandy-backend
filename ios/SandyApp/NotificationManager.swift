import Foundation
import UserNotifications

// ─────────────────────────────────────────────────────────────────────────
//  NotificationManager — مدير الإشعارات المحلية المركزي.
//
//  يطلب الإذن مرّة، ويجدول إشعارًا لكل عنصر إله وقت مستقبلي (تذكير/رسالة
//  مستقبلية…). هوية الإشعار = بادئة النوع + هوية العنصر، فإعادة الجدولة تستبدل
//  القديم بلا تكرار، والمواعيد الماضية تُتجاهل.
//
//  الإشعار المحلي بيوصل والتطبيق مسكّر/مقفول (النظام يطلّعه) طالما تجدول مسبقًا
//  والإذن مُعطى. هاد أساس مستقل تمامًا عن الدفع البعيد (APNs) — لاحقًا بنركّب
//  الدفع فوقه (تسجيل توكن + إرسال من الباك‑إند) بلا ما نلمس هالكود.
//
//  iOS 16-safe — UserNotifications فقط. الصنف thread-safe (UNUserNotificationCenter
//  آمن للنداء من أي خيط) فما نعزله بـ main actor.
// ─────────────────────────────────────────────────────────────────────────

/// عنصر قابل للجدولة — يبنيه الستور من بياناته.
struct NotificationItem {
    let id: String
    let title: String
    let body: String
    let date: Date
}

/// وجهة النقر على الإشعار — الشاشة اللي نفتحها حسب نوع الإشعار.
enum NotifRoute: String, Identifiable {
    case reminders, tasks, future
    var id: String { rawValue }
}

final class NotificationManager: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationManager()
    private let center = UNUserNotificationCenter.current()

    /// تُضبط عند النقر على إشعار → الواجهة تفتح شاشتها. تُصفّر بعد الفتح.
    @Published var pendingRoute: NotifRoute?

    private override init() {
        super.init()
        // مندوب المركز — حتى يطلع الإشعار كبانر والتطبيق مفتوح، ونمسك النقر للتوجيه.
        center.delegate = self
    }

    /// نطلب الإذن (تنبيه/صوت/شارة). آمن للنداء المتكرّر — النظام يعرضه مرّة.
    func requestAuthorization() {
        center.requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    /// التطبيق مفتوح: نعرض الإشعار كبانر + صوت + ضمن قائمة الإشعارات.
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler:
                                    @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .list])
    }

    /// النقر على الإشعار: نقرأ نوعه من بادئة الهوية ونوجّه الواجهة لشاشته.
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let id = response.notification.request.identifier
        let route: NotifRoute? =
            id.hasPrefix("reminder.") ? .reminders :
            id.hasPrefix("task.")     ? .tasks :
            id.hasPrefix("future.")   ? .future : nil
        if let route {
            DispatchQueue.main.async { self.pendingRoute = route }
        }
        completionHandler()
    }

    /// نزامن إشعارات نوع كامل بنفس البادئة: نلغي كل المعلّق بهالبادئة ثم نجدول
    /// العناصر المستقبلية. البادئة تفصل الأنواع فما يتعارضوا (تذكير/رسالة/…).
    func sync(prefix: String, items: [NotificationItem]) {
        center.getPendingNotificationRequests { [weak self] reqs in
            guard let self else { return }
            let stale = reqs.map(\.identifier).filter { $0.hasPrefix(prefix) }
            self.center.removePendingNotificationRequests(withIdentifiers: stale)
            for it in items {
                self.schedule(id: prefix + it.id, title: it.title, body: it.body, at: it.date)
            }
        }
    }

    /// إشعار واحد بهوية ثابتة (يستبدل أي قديم بنفس الهوية). الماضي يُتجاهل.
    private func schedule(id: String, title: String, body: String, at date: Date) {
        guard date > Date() else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let comps = Calendar.current.dateComponents(
            [.year, .month, .day, .hour, .minute], from: date)
        let trigger = UNCalendarNotificationTrigger(dateMatching: comps, repeats: false)
        center.add(UNNotificationRequest(identifier: id, content: content, trigger: trigger))
    }

    /// مُحلِّل ISO متسامح — الباك‑إند قد يرسل بمنطقة زمنية، بكسور ثانية، أو بدون.
    static func parseISO(_ s: String) -> Date? {
        if s.isEmpty { return nil }
        let isoFrac = ISO8601DateFormatter()
        isoFrac.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = isoFrac.date(from: s) { return d }
        let isoPlain = ISO8601DateFormatter()
        isoPlain.formatOptions = [.withInternetDateTime]
        if let d = isoPlain.date(from: s) { return d }
        // بدون منطقة زمنية (مثل "2026-06-05T16:00:00") — نفسّره بالتوقيت المحلي.
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.date(from: s)
    }
}
