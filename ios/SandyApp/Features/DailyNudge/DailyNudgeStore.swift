import SwiftUI

/// بطاقة التنبيه اليومي على الرئيسية (المرحلة السابعة).
///
/// مرّة باليوم ساندي بتقلك إشي مبادر: يوم بيوم سؤال تعارف يبني ملفك بالتدريج
/// (بدل جدار تعارف أول مرّة)، وباقي الأيام جملة عن مهام يومك مكتوبة بشخصيتها
/// (تحذير لطيف لو مضغوط، تطمين لو خفيف). المحتوى من `/api/daily-nudge` المخزّن
/// باليوم، فما يتكرّر. هاد المسار المجاني (بدون مفاتيح آبل) — نفس التنبيه بيوصل
/// كدفع بعيد لما التطبيق مسكّر بعد ما تُضاف مفاتيح آبل بالسيرفر.
@MainActor
final class DailyNudgeStore: ObservableObject {
    @Published var nudge: DailyNudge?
    @Published var answer: String = ""
    @Published var submitting = false
    @Published var answered = false
    @Published var dismissed = false

    private var loaded = false

    /// اليوم اللي انسكّرت فيه البطاقة — محفوظ ع الجهاز.
    ///
    /// **كان `dismissed` بالذاكرة وبس.** تسكّر البطاقة، تطلع من التطبيق،
    /// وترجع — بتلاقيها قدّامك. يعني زرّ الإغلاق ما كان يغلق إشي، كان يخفيه
    /// لحدّ ما تنسى.
    ///
    /// محفوظ **باليوم** مش كعلَم: تنبيه بكرا لازم يظهر. لو خزّنّا «انسكّر»
    /// وبس، أول إغلاق بيطفّي الميزة للأبد.
    private static let dismissKey = "sandy.nudge.dismissedOn"

    private var todayKey: String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }

    /// يجلب تنبيه اليوم مرّة (بصمت — التنبيه ميزة لطيفة مش حرجة، فأي فشل بينخفي).
    func loadIfNeeded(api: APIClient) async {
        guard !loaded else { return }
        loaded = true
        dismissed = UserDefaults.standard.string(forKey: Self.dismissKey) == todayKey
        nudge = try? await api.getDailyNudge()
    }

    /// إغلاق بيدوم. البطاقة ما بترجع اليوم، وبترجع بكرا بمحتوى جديد.
    func dismiss() {
        dismissed = true
        UserDefaults.standard.set(todayKey, forKey: Self.dismissKey)
    }

    /// يرسل جواب سؤال التعارف ويخفي البطاقة (اليوم خلص).
    func submit(api: APIClient) async {
        guard let n = nudge, n.isQuestion,
              !answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        submitting = true
        defer { submitting = false }
        do {
            try await api.answerDailyNudge(qid: n.qid, answer: answer)
            answered = true
        } catch {
            // فشل الإرسال — نخلّي البطاقة حتى يعيد المحاولة.
        }
    }

    /// هل نعرض البطاقة أصلاً؟ لا لو ما في محتوى، أو أُجيب/أُغلق اليوم.
    var isVisible: Bool {
        guard let n = nudge, n.hasContent, !dismissed, !answered else { return false }
        return true
    }
}
