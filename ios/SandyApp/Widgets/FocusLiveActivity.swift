import ActivityKit
import Combine
import Foundation

/// جلسة التركيز على شاشة القفل والجزيرة الديناميكية.
///
/// مصدر الحقيقة هو الخادم (`/api/life/focus`)؛ شاشة المؤقّت بتنادي `sync` بعد كل
/// جلب، وهاد بيبدأ النشاط، أو بيحدّثه لما يتغيّر الطور/الدورة، أو بينهيه لما
/// تخلص الجلسة. العدّ التنازلي نفسه بيرسمه النظام من مدى زمني، فبيضل يمشي
/// والتطبيق نايم.
///
/// ملاحظة: iOS ما بيسمح لتطبيق يشغّل وضع «التركيز» تبع النظام — هاد عرض بس.
@MainActor
final class FocusLiveActivity {
    static let shared = FocusLiveActivity()

    /// بتنطلق لما الجلسة تتغيّر من برّا الشاشة (زر «إنهاء» بالجزيرة) — شاشة
    /// المؤقّت بتسمعها وبتعيد الجلب.
    let changed = PassthroughSubject<Void, Never>()

    private var activity: Activity<SandyFocusAttributes>?
    private var lastState: SandyFocusAttributes.ContentState?

    /// يطابق النشاط مع حالة الجلسة من الخادم.
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

        // نفس الطور والدورة ونفس النهاية تقريبًا (فرق ثواني الشبكة)؟ ما في داعي نحدّث.
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

    /// ينهي النشاط فورًا (وأي نشاط تركيز متروك من تشغيل سابق).
    func end() {
        lastState = nil
        activity = nil
        let all = Activity<SandyFocusAttributes>.activities
        guard !all.isEmpty else { return }
        Task {
            for a in all { await a.end(nil, dismissalPolicy: .immediate) }
        }
    }

    /// `sandy://focus/stop` من زر الجزيرة/شاشة القفل: ينهي الجلسة بالخادم
    /// (كجلسة مكتملة، مش ملغاة) ويشيل النشاط.
    func stopFromLink() {
        Task {
            let api = APIClient(baseURL: Backend.currentURL)   // التوكن من الـKeychain
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
