import SwiftUI

/// The tasks Sandy runs on her own: each with its state and what is new, and the email
/// their results go to. Made and changed by talk; here they are seen, paused, resumed and
/// removed.
struct ScheduledTasksView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store = ScheduledTasksStore()

    var body: some View {
        List {
            if !store.notice.isEmpty {
                SandyNotice(store.notice, kind: .gentleWarning).listRowBackground(Color.clear)
            }
            Section {
                if store.tasks.isEmpty && !store.loading {
                    Text(lang.s("tasks.empty"))
                        .font(Theme.Typography.body)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
                ForEach(store.tasks) { task in
                    NavigationLink {
                        ScheduledTaskView(taskId: task.id, store: store)
                    } label: {
                        row(task)
                    }
                }
            }
            if let mail = store.email {
                EmailSection(mail: mail, store: store)
            }
        }
        .overlay { if store.loading && store.tasks.isEmpty { ProgressView() } }
        .navigationTitle(lang.s("tasks.title"))
        .navigationBarTitleDisplayMode(.inline)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .modifier(TasksFollow(store: store))
    }

    private func row(_ task: ScheduledTask) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(task.title).font(Theme.Typography.headline).lineLimit(1)
                Spacer(minLength: 0)
                if task.unseen > 0 {
                    Text(String(format: lang.s("tasks.unseen"), number(task.unseen)))
                        .font(Theme.Typography.caption.weight(.semibold))
                        .foregroundColor(Theme.Colors.accent)
                }
            }
            Text(TaskFormat.state(task, lang))
                .font(Theme.Typography.caption)
                .foregroundColor(task.paused ? Theme.Colors.tertiaryText : Theme.Colors.secondaryText)
        }
        .accessibilityElement(children: .combine)
    }

    private func number(_ n: Int) -> String { n.formatted(.number.locale(AppLocale.current)) }
}

/// Where results are emailed: the address, whether it is confirmed, the link and stopping.
private struct EmailSection: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    let mail: NotifyEmail
    @ObservedObject var store: ScheduledTasksStore
    @State private var address = ""
    @State private var sending = false

    var body: some View {
        Section {
            if !mail.ready {
                Text(lang.s("tasks.notReady")).foregroundColor(Theme.Colors.secondaryText)
            } else if !mail.address.isEmpty {
                LabeledContent(mail.address,
                               value: lang.s(mail.confirmed ? "tasks.confirmed" : "tasks.waiting"))
                if !mail.confirmed {
                    Button(lang.s("tasks.sendLink")) { ask(mail.address) }.disabled(sending)
                }
                Button(lang.s("tasks.stopEmail"), role: .destructive) {
                    Task { await store.forgetEmail(api: state.api) }
                }
            } else {
                TextField(lang.s("tasks.emailPlaceholder"), text: $address)
                    .keyboardType(.emailAddress)
                    .textContentType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button(lang.s("tasks.sendLink")) { ask(address) }
                    .disabled(sending || address.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        } header: {
            Text(lang.s("tasks.email"))
        } footer: {
            Text(lang.s("tasks.emailNote"))
        }
    }

    private func ask(_ value: String) {
        sending = true
        Task {
            if await store.askEmail(value, api: state.api) { address = "" }
            sending = false
        }
    }
}

/// One task: what it does, its state, pause or resume, remove, and what it found.
struct ScheduledTaskView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let taskId: String
    @ObservedObject var store: ScheduledTasksStore
    @State private var confirmRemove = false
    @State private var editing = false

    private var task: ScheduledTask? { store.tasks.first { $0.id == taskId } }

    var body: some View {
        List {
            if !store.notice.isEmpty {
                SandyNotice(store.notice, kind: .gentleWarning).listRowBackground(Color.clear)
            }
            if let task {
                Section {
                    LabeledContent(lang.s("tasks.instructions"), value: task.instructions)
                    Text(TaskFormat.state(task, lang))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                    LabeledContent(lang.s("tasks.how"), value: TaskFormat.how(task.way, lang))
                        .font(Theme.Typography.caption)
                    Button(lang.s("tasks.edit")) { editing = true }
                    if task.failures > 0 && !task.lastError.isEmpty {
                        LabeledContent(lang.s("tasks.lastError"), value: task.lastError)
                            .font(Theme.Typography.caption)
                    }
                    Button(lang.s(task.paused ? "tasks.resume" : "tasks.pause")) {
                        Task { await store.setPaused(!task.paused, id: task.id, api: state.api) }
                    }
                    Button(lang.s("tasks.remove"), role: .destructive) { confirmRemove = true }
                        .confirmationDialog(lang.s("tasks.removeAsk"), isPresented: $confirmRemove,
                                            titleVisibility: .visible) {
                            Button(lang.s("tasks.remove"), role: .destructive) {
                                Task {
                                    await store.remove(id: task.id, api: state.api)
                                    if store.notice.isEmpty { dismiss() }
                                }
                            }
                        }
                }
            }
            Section(lang.s("tasks.results")) {
                if store.results.isEmpty && !store.loading {
                    Text(lang.s("tasks.noResults")).foregroundColor(Theme.Colors.secondaryText)
                }
                ForEach(store.results) { result in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(result.body).font(Theme.Typography.body).textSelection(.enabled)
                        if let date = result.date {
                            Text(date.formatted(.dateTime.locale(AppLocale.current)))
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.tertiaryText)
                        }
                    }
                }
            }
        }
        .sheet(isPresented: $editing) {
            if let task { TaskEditSheet(task: task, store: store) }
        }
        .navigationTitle(task?.title ?? lang.s("tasks.title"))
        .navigationBarTitleDisplayMode(.inline)
        .task {
            store.results = []
            await store.open(taskId, api: state.api)
        }
        .refreshable { await store.open(taskId, api: state.api) }
    }
}

/// A change made anywhere else shows here at once: after a chat turn or a call (theirs end
/// in `sandyBlocksChanged`), on the server's `{"sync": "tasks"}` push, back in the front, and
/// every `TasksFollow.every` while the screen is open (pushes may not be set up, or held).
struct TasksFollow: ViewModifier {
    static let every: Duration = .seconds(20)
    @EnvironmentObject var state: AppState
    @Environment(\.scenePhase) private var phase
    @ObservedObject var store: ScheduledTasksStore

    func body(content: Content) -> some View {
        content
            .onReceive(NotificationCenter.default.publisher(for: .sandyBlocksChanged)) { _ in
                Task { await store.refresh(api: state.api) }
            }
            .onReceive(NotificationCenter.default.publisher(for: .sandyTasksChanged)) { _ in
                Task { await store.refresh(api: state.api) }
            }
            .onChange(of: phase) { _, now in
                if now == .active { Task { await store.refresh(api: state.api) } }
            }
            .task {
                while !Task.isCancelled {
                    try? await Task.sleep(for: Self.every)
                    if Task.isCancelled { break }
                    if phase == .active { await store.refresh(api: state.api) }
                }
            }
    }
}

enum TaskFormat {
    /// «شغّالة · كل ساعة · الجاية: ١٠:٠٠».
    @MainActor
    static func state(_ task: ScheduledTask, _ lang: LanguageManager) -> String {
        var parts = [lang.s(task.paused ? "tasks.paused" : "tasks.running"), every(task.everyMinutes, lang)]
        if !task.paused, let next = task.nextDate {
            parts.append(String(format: lang.s("tasks.next"),
                                next.formatted(.dateTime.weekday().hour().minute().locale(AppLocale.current))))
        }
        if task.failures > 0 {
            parts.append(String(format: lang.s("tasks.failures"),
                                task.failures.formatted(.number.locale(AppLocale.current))))
        }
        return parts.joined(separator: " · ")
    }

    /// «فوراً كل ما يتغيّر», «ملخص مرة باليوم الساعة ٢١:٠٠», «بالكتير مرة كل ٣ ساعة».
    @MainActor
    static func how(_ way: TaskDelivery, _ lang: LanguageManager) -> String { how(way, in: lang.lang) }

    static func how(_ way: TaskDelivery, in lang: AppLang) -> String {
        switch way.mode {
        case TaskDelivery.instant: return translate(lang, "tasks.howInstant")
        case TaskDelivery.daily: return String(format: translate(lang, "tasks.howDailyAt"), way.at ?? "")
        default:
            let n = way.hours ?? 1
            return n == 1 ? translate(lang, "tasks.howHourly")
                : String(format: translate(lang, "tasks.howEverySpan"), span(n, "hour", in: lang))
        }
    }

    @MainActor
    static func every(_ minutes: Int, _ lang: LanguageManager) -> String { every(minutes, in: lang.lang) }

    /// «كل دقيقة», «كل ساعتين», «كل ٣ ساعات», «كل يوم»; «every minute», «every two hours», as
    /// Sandy says it in the chat.
    static func every(_ minutes: Int, in lang: AppLang) -> String {
        let m = max(minutes, 1)
        let (n, unit) = m % 1440 == 0 ? (m / 1440, "day") : m % 60 == 0 ? (m / 60, "hour") : (m, "minute")
        return String(format: translate(lang, "tasks.every"), span(n, unit, in: lang))
    }

    /// One, two, three to ten, eleven on, as each language counts them; English spells two to ten.
    static func span(_ n: Int, _ unit: String, in lang: AppLang) -> String {
        let size = n == 1 ? "One" : n == 2 ? "Two" : n <= 10 ? "Few" : "Many"
        let key = "tasks.\(unit)\(size)"
        guard size == "Few" || size == "Many" else { return translate(lang, key) }
        let number: String
        if lang == .en && n <= 10 {
            let words = NumberFormatter()
            words.locale = Locale(identifier: "en")
            words.numberStyle = .spellOut
            number = words.string(from: NSNumber(value: n)) ?? "\(n)"
        } else {
            number = n.formatted(.number.locale(AppLocale.locale(for: lang)))
        }
        return String(format: translate(lang, key), number)
    }
}
