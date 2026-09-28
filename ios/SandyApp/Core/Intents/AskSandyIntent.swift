import AppIntents
import Foundation

// «اسأل ساندي» من سيري بدون فتح التطبيق؛ بيروح لـ POST /api/agent بنفس خيط المستخدم.

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

    // اختياري: عبارة سيري ما فيها نص حر، فسيري بتسأل عنه.
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
        let res: AskSandyResponse = try await api.fetch("/api/agent",
                                                        method: "POST",
                                                        body: AskSandyRequestBody(message: q),
                                                        timeout: 60)
        // سيري بتقرا علامات الماركداون حرفياً.
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
