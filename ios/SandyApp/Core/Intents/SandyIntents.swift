import AppIntents
import Foundation

// كل نية بتنشئ APIClient خاص (التوكن من الـKeychain) فبتشتغل بمعزل عن واجهة التطبيق.

enum IntentAPI {
    static func make() throws -> APIClient {
        // نفس مصدر التطبيق حتى الاختصارات تتبع أي تغيير للخادم.
        let api = APIClient(baseURL: Backend.currentURL)
        guard api.token != nil else { throw SandyIntentError.notSignedIn }
        return api
    }

    static var isArabic: Bool {
        Locale.current.language.languageCode?.identifier == "ar"
    }

    static func say(_ ar: String, _ en: String) -> LocalizedStringResource {
        LocalizedStringResource(stringLiteral: isArabic ? ar : en)
    }

    static func dialog(_ ar: String, _ en: String) -> IntentDialog {
        IntentDialog(stringLiteral: isArabic ? ar : en)
    }
}

enum SandyIntentError: Error, CustomLocalizedStringResourceConvertible {
    case notSignedIn
    case commandNotSupported(String)
    case buttonNotLearned(String, String)
    case notReached(String)
    case notConnected(String)

    var localizedStringResource: LocalizedStringResource {
        switch self {
        case .notSignedIn:
            return IntentAPI.say("افتح ساندي وسجّل دخول أول.",
                                 "Open Sandy and sign in first.")
        case .commandNotSupported(let device):
            return IntentAPI.say("\(device) ما بيقبل هالأمر.",
                                 "\(device) doesn't support that command.")
        case .buttonNotLearned(let button, let device):
            return IntentAPI.say("زر \(button) مش متعلّم على \(device) بعد.",
                                 "The \(button) button isn't learned on \(device) yet.")
        case .notReached(let device):
            return IntentAPI.say("الأمر ما وصل لـ\(device). جرّب كمان شوي.",
                                 "That didn't reach \(device). Try again in a moment.")
        case .notConnected(let device):
            return IntentAPI.say("\(device) مش متّصل هلّق، فما بعتّله الأمر.",
                                 "\(device) isn't connected right now, so nothing was sent.")
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
        try await api.addItem(list: "tasks", text: text)
        return .result(dialog: IntentAPI.dialog("ضفت المهمة: \(text)", "Added task: \(text)"))
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
        try await api.addSchedule(text: text, at: date)
        return .result(dialog: IntentAPI.dialog("ضفت التذكير: \(text)", "Added reminder: \(text)"))
    }
}

struct AddHabitIntent: AppIntent {
    static var title: LocalizedStringResource = "Add Habit"
    static var description = IntentDescription("Add a new habit to Sandy.")

    @Parameter(title: "Habit") var name: String

    static var parameterSummary: some ParameterSummary { Summary("Add habit \(\.$name)") }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addItem(list: "habits", text: name)
        return .result(dialog: IntentAPI.dialog("ضفت العادة: \(name)", "Added habit: \(name)"))
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
        // The server needs some text; an expense said with no note is just «مصروف».
        let label = note.flatMap { $0.isEmpty ? nil : $0 } ?? (IntentAPI.isArabic ? "مصروف" : "Expense")
        try await api.addEntry(kind: "expense", text: label, data: ["amount": .number(amount)])
        return .result(dialog: IntentAPI.dialog("سجّلت مصروف بمبلغ \(amount)", "Logged expense: \(amount)"))
    }
}

struct AddJournalIntent: AppIntent {
    static var title: LocalizedStringResource = "Add Journal Note"
    static var description = IntentDescription("Add a note to your Sandy journal.")

    @Parameter(title: "Journal note") var text: String

    static var parameterSummary: some ParameterSummary { Summary("Add journal note \(\.$text)") }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        try await api.addEntry(kind: "journal", text: text)
        return .result(dialog: IntentAPI.dialog("ضفت الخاطرة بدفترك.", "Added to your journal."))
    }
}

// MARK: - مزوّد الاختصارات

struct SandyShortcuts: AppShortcutsProvider {
    // حد أبل: عشرة اختصارات بالكثير لكل تطبيق — هون صاروا عشرة.
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: AskSandyIntent(),
                    phrases: ["اسأل ساندي في \(.applicationName)",
                              "اسأل \(.applicationName)",
                              "Ask \(.applicationName)",
                              "Ask \(.applicationName) a question"],
                    shortTitle: "Ask Sandy", systemImageName: "questionmark.bubble.fill")
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
        AppShortcut(intent: ControlDeviceIntent(command: .on),
                    phrases: ["شغّل \(\.$device) في \(.applicationName)",
                              "Turn on \(\.$device) in \(.applicationName)"],
                    shortTitle: "Turn On", systemImageName: "power")
        AppShortcut(intent: ControlDeviceIntent(command: .off),
                    phrases: ["طفّي \(\.$device) في \(.applicationName)",
                              "Turn off \(\.$device) in \(.applicationName)"],
                    shortTitle: "Turn Off", systemImageName: "power.circle")
        AppShortcut(intent: ControlDeviceIntent(command: .open),
                    phrases: ["افتح \(\.$device) في \(.applicationName)",
                              "Open \(\.$device) in \(.applicationName)"],
                    shortTitle: "Open", systemImageName: "curtains.open")
        AppShortcut(intent: ControlDeviceIntent(command: .close),
                    phrases: ["سكّر \(\.$device) في \(.applicationName)",
                              "Close \(\.$device) in \(.applicationName)"],
                    shortTitle: "Close", systemImageName: "curtains.closed")
    }
}
