import AppIntents
import Foundation

// ─────────────────────────────────────────────────────────────────────────
//  SandyIntents — نوايا App Intents: تظهر بسيري + تطبيق شورتكتس + سبوتلايت.
//
//  كل نية تنشئ APIClient خاص فيها (التوكن يتحمّل من الـKeychain تلقائياً، وعنوان
//  الخادم من UserDefaults أو الافتراضي)، فتقدر تصادق الباك‑إند وهي شغّالة بمعزل
//  عن واجهة التطبيق. لو ما في توكن (مش مسجّل دخول) ترمي رسالة ودّية.
//
//  لا تحتاج تارجت جديد — تعيش بتارجت التطبيق. التطبيق هدفه iOS 18.5 فـ App Intents
//  (iOS 16+) متاحة دايمًا.
// ─────────────────────────────────────────────────────────────────────────

/// أدوات مشتركة للنوايا — بناء عميل مصادَق + حارس الدخول.
enum IntentAPI {
    private static let defaultBaseURL = "https://sandy-robot-3da0693d32f7.herokuapp.com"

    static func make() throws -> APIClient {
        let base = UserDefaults.standard.string(forKey: "sandy_base_url") ?? defaultBaseURL
        let api = APIClient(baseURL: base)   // التوكن يتحمّل من الـKeychain بالـinit
        guard api.token != nil else { throw SandyIntentError.notSignedIn }
        return api
    }

    /// مُنسّق ISO للموعد (تذكير) — نفس ما يفهمه الباك‑إند.
    static func iso(_ date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }
}

enum SandyIntentError: Error, CustomLocalizedStringResourceConvertible {
    case notSignedIn
    var localizedStringResource: LocalizedStringResource {
        switch self {
        case .notSignedIn: return "افتح ساندي وسجّل دخول أول."
        }
    }
}

// MARK: - النوايا

struct AddTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "إضافة مهمة"
    static var description = IntentDescription("أضف مهمة جديدة لساندي.")

    @Parameter(title: "المهمة") var text: String

    static var parameterSummary: some ParameterSummary { Summary("أضف مهمة \(\.$text)") }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addTask(text: text)
        return .result(dialog: "ضفت المهمة: \(text)")
    }
}

struct AddReminderIntent: AppIntent {
    static var title: LocalizedStringResource = "إضافة تذكير"
    static var description = IntentDescription("أضف تذكير بموعد لساندي.")

    @Parameter(title: "التذكير") var text: String
    @Parameter(title: "الموعد") var date: Date

    static var parameterSummary: some ParameterSummary {
        Summary("ذكّرني بـ \(\.$text) يوم \(\.$date)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addReminder(text: text, remindAt: IntentAPI.iso(date), note: nil)
        return .result(dialog: "ضفت التذكير: \(text)")
    }
}

struct AddHabitIntent: AppIntent {
    static var title: LocalizedStringResource = "إضافة عادة"
    static var description = IntentDescription("أضف عادة جديدة لساندي.")

    @Parameter(title: "العادة") var name: String

    static var parameterSummary: some ParameterSummary { Summary("أضف عادة \(\.$name)") }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addHabit(name: name)
        return .result(dialog: "ضفت العادة: \(name)")
    }
}

struct AddExpenseIntent: AppIntent {
    static var title: LocalizedStringResource = "إضافة مصروف"
    static var description = IntentDescription("سجّل مصروف بمبلغ لساندي.")

    @Parameter(title: "المبلغ") var amount: Double
    @Parameter(title: "الملاحظة") var note: String?

    static var parameterSummary: some ParameterSummary {
        Summary("سجّل مصروف \(\.$amount)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addExpense(amount: amount, note: note ?? "", category: "")
        return .result(dialog: "سجّلت مصروف بمبلغ \(amount)")
    }
}

struct AddJournalIntent: AppIntent {
    static var title: LocalizedStringResource = "إضافة يومية"
    static var description = IntentDescription("أضف خاطرة لدفتر يومياتك بساندي.")

    @Parameter(title: "الخاطرة") var text: String

    static var parameterSummary: some ParameterSummary { Summary("أضف خاطرة \(\.$text)") }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addJournalEntry(text: text)
        return .result(dialog: "ضفت الخاطرة بدفترك.")
    }
}

// MARK: - مزوّد الاختصارات (يطلّع النوايا بسيري + شورتكتس + سبوتلايت)

struct SandyShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: AddTaskIntent(),
                    phrases: ["أضف مهمة في \(.applicationName)",
                              "Add a task in \(.applicationName)"],
                    shortTitle: "إضافة مهمة", systemImageName: "checklist")
        AppShortcut(intent: AddReminderIntent(),
                    phrases: ["أضف تذكير في \(.applicationName)",
                              "Add a reminder in \(.applicationName)"],
                    shortTitle: "إضافة تذكير", systemImageName: "bell.fill")
        AppShortcut(intent: AddHabitIntent(),
                    phrases: ["أضف عادة في \(.applicationName)",
                              "Add a habit in \(.applicationName)"],
                    shortTitle: "إضافة عادة", systemImageName: "flame.fill")
        AppShortcut(intent: AddExpenseIntent(),
                    phrases: ["سجّل مصروف في \(.applicationName)",
                              "Log an expense in \(.applicationName)"],
                    shortTitle: "إضافة مصروف", systemImageName: "creditcard.fill")
        AppShortcut(intent: AddJournalIntent(),
                    phrases: ["أضف خاطرة في \(.applicationName)",
                              "Add a journal note in \(.applicationName)"],
                    shortTitle: "إضافة يومية", systemImageName: "book.closed.fill")
    }
}
