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

    /// يجلب تنبيه اليوم مرّة (بصمت — التنبيه ميزة لطيفة مش حرجة، فأي فشل بينخفي).
    func loadIfNeeded(api: APIClient) async {
        guard !loaded else { return }
        loaded = true
        nudge = try? await api.getDailyNudge()
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

struct DailyNudgeCard: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var store: DailyNudgeStore
    @FocusState private var answerFocused: Bool

    var body: some View {
        Group {
            if store.isVisible, let n = store.nudge {
                SandyCard(padding: Theme.Spacing.md) {
                    VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                        header
                        Text(n.text)
                            .font(Theme.Typography.body)
                            .foregroundColor(Theme.Colors.primaryText)
                            .fixedSize(horizontal: false, vertical: true)

                        if n.isQuestion {
                            answerField
                        }
                    }
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .animation(.easeInOut(duration: 0.25), value: store.isVisible)
    }

    // ترويسة: وجه ساندي + عنوان + زر إغلاق (لجملة المهام؛ السؤال يُخفى بالجواب).
    private var header: some View {
        HStack(spacing: Theme.Spacing.sm) {
            SandyAvatar(size: 30, mood: .happy)
            Text(lang.s("nudge.title"))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.accentSoft)
            Spacer(minLength: 0)
            if store.nudge?.isQuestion == false {
                Button { store.dismissed = true } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 18))
                        .foregroundColor(Theme.Colors.secondaryText)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(lang.s("nudge.dismiss"))
            }
        }
    }

    // حقل جواب سؤال التعارف + زر الإرسال.
    private var answerField: some View {
        HStack(spacing: Theme.Spacing.sm) {
            TextField(lang.s("nudge.answer.placeholder"), text: $store.answer)
                .textFieldStyle(.plain)
                .font(Theme.Typography.body)
                .foregroundColor(Theme.Colors.primaryText)
                .focused($answerFocused)
                .padding(.vertical, Theme.Spacing.sm)
                .padding(.horizontal, Theme.Spacing.md)
                .background(Theme.Colors.surface)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                .submitLabel(.send)
                .onSubmit { send() }

            SandyButton(title: lang.s("nudge.answer.send"),
                        isLoading: store.submitting) { send() }
        }
    }

    private func send() {
        answerFocused = false
        Task { await store.submit(api: state.api) }
    }
}
