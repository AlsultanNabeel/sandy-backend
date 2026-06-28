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

    /// هل لغة الجهاز عربي؟ — لاختيار لغة ردّ سيري.
    static var isArabic: Bool {
        Locale.current.language.languageCode?.identifier == "ar"
    }

    /// يختار النص حسب لغة الجهاز.
    static func say(_ ar: String, _ en: String) -> LocalizedStringResource {
        LocalizedStringResource(stringLiteral: isArabic ? ar : en)
    }
}

enum SandyIntentError: Error, CustomLocalizedStringResourceConvertible {
    case notSignedIn
    var localizedStringResource: LocalizedStringResource {
        switch self {
        case .notSignedIn: return IntentAPI.say("افتح ساندي وسجّل دخول أول.",
                                               "Open Sandy and sign in first.")
        }
    }
}

// MARK: - النوايا

struct AddTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "Add Task"
    static var description = IntentDescription("Add a new task to Sandy.")

    @Parameter(title: "Task") var text: String

    static var parameterSummary: some ParameterSummary { Summary("Add task \(\.$text)") }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addTask(text: text)
        return .result(dialog: IntentAPI.say("ضفت المهمة: \(text)", "Added task: \(text)"))
    }
}

struct AddReminderIntent: AppIntent {
    static var title: LocalizedStringResource = "Add Reminder"
    static var description = IntentDescription("Add a timed reminder to Sandy.")

    @Parameter(title: "Reminder") var text: String
    @Parameter(title: "Date") var date: Date

    static var parameterSummary: some ParameterSummary {
        Summary("Remind me to \(\.$text) on \(\.$date)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addReminder(text: text, remindAt: IntentAPI.iso(date), note: nil)
        return .result(dialog: IntentAPI.say("ضفت التذكير: \(text)", "Added reminder: \(text)"))
    }
}

struct AddHabitIntent: AppIntent {
    static var title: LocalizedStringResource = "Add Habit"
    static var description = IntentDescription("Add a new habit to Sandy.")

    @Parameter(title: "Habit") var name: String

    static var parameterSummary: some ParameterSummary { Summary("Add habit \(\.$name)") }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addHabit(name: name)
        return .result(dialog: IntentAPI.say("ضفت العادة: \(name)", "Added habit: \(name)"))
    }
}

struct AddExpenseIntent: AppIntent {
    static var title: LocalizedStringResource = "Add Expense"
    static var description = IntentDescription("Log an expense in Sandy.")

    @Parameter(title: "Amount") var amount: Double
    @Parameter(title: "Note") var note: String?

    static var parameterSummary: some ParameterSummary {
        Summary("Log expense \(\.$amount)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addExpense(amount: amount, note: note ?? "", category: "")
        return .result(dialog: IntentAPI.say("سجّلت مصروف بمبلغ \(amount)", "Logged expense: \(amount)"))
    }
}

struct AddJournalIntent: AppIntent {
    static var title: LocalizedStringResource = "Add Journal Note"
    static var description = IntentDescription("Add a note to your Sandy journal.")

    @Parameter(title: "Journal note") var text: String

    static var parameterSummary: some ParameterSummary { Summary("Add journal note \(\.$text)") }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addJournalEntry(text: text)
        return .result(dialog: IntentAPI.say("ضفت الخاطرة بدفترك.", "Added to your journal."))
    }
}

// MARK: - مزوّد الاختصارات (يطلّع النوايا بسيري + شورتكتس + سبوتلايت)

struct SandyShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: AddTaskIntent(),
                    phrases: ["أضف مهمة في \(.applicationName)",
                              "Add a task in \(.applicationName)"],
                    shortTitle: "Add Task", systemImageName: "checklist")
        AppShortcut(intent: AddReminderIntent(),
                    phrases: ["أضف تذكير في \(.applicationName)",
                              "Add a reminder in \(.applicationName)"],
                    shortTitle: "Add Reminder", systemImageName: "bell.fill")
        AppShortcut(intent: AddHabitIntent(),
                    phrases: ["أضف عادة في \(.applicationName)",
                              "Add a habit in \(.applicationName)"],
                    shortTitle: "Add Habit", systemImageName: "flame.fill")
        AppShortcut(intent: AddExpenseIntent(),
                    phrases: ["سجّل مصروف في \(.applicationName)",
                              "Log an expense in \(.applicationName)"],
                    shortTitle: "Add Expense", systemImageName: "creditcard.fill")
        AppShortcut(intent: AddJournalIntent(),
                    phrases: ["أضف خاطرة في \(.applicationName)",
                              "Add a journal note in \(.applicationName)"],
                    shortTitle: "Add Journal Note", systemImageName: "book.closed.fill")
    }
}
