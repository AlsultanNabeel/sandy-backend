import AppIntents
import Foundation

// ─────────────────────────────────────────────────────────────────────────
//  AskSandyIntent — «اسأل ساندي» من سيري بدون ما ينفتح التطبيق.
//
//  السؤال بيروح لنفس الدردشة (POST /api/agent غير الستريمنغ، جسمه
//  {"message": …}) بنفس خيط المستخدم، فساندي بتتذكّر السؤال بعدين بالتطبيق.
//  الرد بيرجع كحوار سيري (بتحكيه بصوت) وكقيمة نصية للاختصارات.
// ─────────────────────────────────────────────────────────────────────────

private struct AskSandyRequestBody: Encodable {
    let message: String
}

private struct AskSandyResponse: Decodable {
    let reply: String?
}

struct AskSandyIntent: AppIntent {
    static var title: LocalizedStringResource = "Ask Sandy"
    static var description = IntentDescription("Ask Sandy anything and hear her answer.")
    static var openAppWhenRun: Bool = false

    // اختياري: عبارة سيري ما فيها نص حر، فسيري بتسأل عنه لما يكون فاضي.
    @Parameter(title: "Question") var question: String?

    static var parameterSummary: some ParameterSummary {
        Summary("Ask Sandy \(\.$question)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> & ProvidesDialog {
        let q = (question ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else {
            throw $question.needsValueError(IntentAPI.dialog("شو بدك تسأل ساندي؟",
                                                             "What do you want to ask Sandy?"))
        }
        let api = try IntentAPI.make()
        // الوكيل ممكن ياخد وقت (أدوات، بحث) — مهلة أطول من الافتراضي.
        let res: AskSandyResponse = try await api.fetch("/api/agent",
                                                        method: "POST",
                                                        body: AskSandyRequestBody(message: q),
                                                        timeout: 60)
        // سيري بتقرا علامات الماركداون حرفياً — منشيل الأكثر شيوعاً.
        let reply = (res.reply ?? "")
            .replacingOccurrences(of: "**", with: "")
            .replacingOccurrences(of: "__", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let text = reply.isEmpty
            ? (IntentAPI.isArabic ? "ما وصلني رد هلّق، جرّب كمان شوي." : "I didn't get an answer just now, try again in a bit.")
            : reply
        return .result(value: text, dialog: IntentDialog(stringLiteral: text))
    }
}
