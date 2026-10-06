import ActivityKit
import Combine
import Foundation

/// جلسة التركيز على شاشة القفل؛ الخادم مصدر الحقيقة وشاشة المؤقّت بتنادي `sync` بعد كل جلب.
/// iOS ما بيسمح لتطبيق يشغّل وضع «التركيز» تبع النظام — هاد عرض بس.
@MainActor
final class FocusLiveActivity {
    static let shared = FocusLiveActivity()

    /// الجلسة تغيّرت من برّا الشاشة (زر «إنهاء» بالجزيرة)، فشاشة المؤقّت بتعيد الجلب.
    let changed = PassthroughSubject<Void, Never>()

    private var activity: Activity<SandyFocusAttributes>?
    private var lastState: SandyFocusAttributes.ContentState?

    func sync(_ status: FocusStatus) {
        guard status.active, !status.demo else { end(); return }

        let now = Date()
        let remaining = max(0, status.remainingSec)
        let total = max(status.totalSec, remaining)
        let ends = now.addingTimeInterval(TimeInterval(remaining))
        let state = SandyFocusAttributes.ContentState(
            phaseStartedAt: ends.addingTimeInterval(-TimeInterval(total)),
            phaseEndsAt: ends,
            isBreak: status.isBreak,
            cycle: status.cycleIdx,
            cycles: status.cycles)

        // نفس الطور والدورة والنهاية تقريبًا؟ ما في داعي نحدّث.
        if let last = lastState, activity != nil,
           last.isBreak == state.isBreak, last.cycle == state.cycle,
           abs(last.phaseEndsAt.timeIntervalSince(state.phaseEndsAt)) < 3 {
            return
        }
        lastState = state
        let content = ActivityContent(state: state,
                                      staleDate: ends.addingTimeInterval(60))

        // بعد إعادة تشغيل التطبيق: نتبنّى النشاط الموجود بدل ما نفتح تاني.
        if activity == nil { activity = Activity<SandyFocusAttributes>.activities.first }

        if let activity {
            Task { await activity.update(content) }
            return
        }
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        activity = try? Activity.request(
            attributes: SandyFocusAttributes(label: status.label, isArabic: AppLocale.isArabic),
            content: content,
            pushType: nil)
    }

    /// وأي نشاط تركيز متروك من تشغيل سابق.
    func end() {
        lastState = nil
        activity = nil
        let all = Activity<SandyFocusAttributes>.activities
        guard !all.isEmpty else { return }
        Task {
            for a in all { await a.end(nil, dismissalPolicy: .immediate) }
        }
    }

    /// ينهي الجلسة بالخادم كمكتملة (مش ملغاة) ويشيل النشاط. Only while a focus activity
    /// is up: sign-out ends it, so a stale «stop» never reaches the next account's session.
    func stopFromLink() {
        guard !Activity<SandyFocusAttributes>.activities.isEmpty else { return }
        Task {
            let api = APIClient(baseURL: Backend.currentURL)
            do {
                try await api.stopFocus(cancel: false)
                Haptics.play(.success)
            } catch {
                Haptics.play(.failure)
            }
            end()
            changed.send()
        }
    }
}
