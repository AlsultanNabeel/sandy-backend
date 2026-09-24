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

    /// Which account the two stored days below belong to.
    ///
    /// They are written to `UserDefaults`, which is one store for the whole
    /// device and outlives the account. Keyed by day alone, the second person
    /// to sign in on this phone inherited the first one's day: their card was
    /// already dismissed, or already answered, before they had seen it — and
    /// the get-to-know-you question they never saw was the one thing that day's
    /// card existed to ask.
    private var userScope = ""

    /// اليوم اللي انسكّرت فيه البطاقة — محفوظ ع الجهاز.
    ///
    /// **كان `dismissed` بالذاكرة وبس.** تسكّر البطاقة، تطلع من التطبيق،
    /// وترجع — بتلاقيها قدّامك. يعني زرّ الإغلاق ما كان يغلق إشي، كان يخفيه
    /// لحدّ ما تنسى.
    ///
    /// محفوظ **باليوم** مش كعلَم: تنبيه بكرا لازم يظهر. لو خزّنّا «انسكّر»
    /// وبس، أول إغلاق بيطفّي الميزة للأبد.
    private static let dismissKey = "sandy.nudge.dismissedOn"
    // نفس المفتاح ونفس الفكرة للجواب.
    //
    // صلّحت الإغلاق وتركت الجواب — وهو نفس العطل بالحرف: `answered` كان
    // بالذاكرة، فتجاوب ع سؤال اليوم، تسكّر التطبيق، وترجع تلاقيه بينتظر جوابك
    // من جديد. الجواب محفوظ ع الخادم فعلًا وما بينسأل بكرا، بس بطاقة اليوم
    // بتضلّ معروضة لأنها انبنت قبل ما تجاوب.
    private static let answerKey = "sandy.nudge.answeredOn"

    /// The stored value carries the account with the day, so a value written by
    /// another account can never match. Keeping it in the value rather than the
    /// key means `dismiss()` needs no `APIClient` to build it.
    private var scopedToday: String { userScope + "|" + todayKey }

    private var todayKey: String {
        // مفتاح تخزين مش نص معروض: تقويم ميلادي وأرقام لاتينية ثابتة، حتى ما
        // يتغيّر المفتاح لو المستخدم بدّل لغة الجهاز أو تقويمه بنص اليوم.
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }

    /// يجلب تنبيه اليوم مرّة (بصمت — التنبيه ميزة لطيفة مش حرجة، فأي فشل بينخفي).
    func loadIfNeeded(api: APIClient) async {
        // A different account is a reload, whatever this store loaded before.
        let uid = api.currentUserId ?? ""
        if uid != userScope {
            userScope = uid
            loaded = false
            nudge = nil
            answer = ""
        }
        guard !loaded else { return }
        loaded = true
        dismissed = UserDefaults.standard.string(forKey: Self.dismissKey) == scopedToday
        answered = UserDefaults.standard.string(forKey: Self.answerKey) == scopedToday
        nudge = try? await api.getDailyNudge()
    }

    /// إغلاق بيدوم. البطاقة ما بترجع اليوم، وبترجع بكرا بمحتوى جديد.
    func dismiss() {
        dismissed = true
        UserDefaults.standard.set(scopedToday, forKey: Self.dismissKey)
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
            UserDefaults.standard.set(scopedToday, forKey: Self.answerKey)
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
