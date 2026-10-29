import SwiftUI

/// Changing a task from the screen, as by talk: what it does, how often it checks, and how it
/// tells. «Review» asks the server for the same question Sandy asks by talk (new words bring
/// their check), and only «Save» on it changes the task.
struct TaskEditSheet: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let task: ScheduledTask
    @ObservedObject var store: ScheduledTasksStore

    @State private var words = ""
    @State private var often = 60
    @State private var inHours = true
    @State private var mode = TaskDelivery.every
    @State private var hours = 1
    @State private var at = Calendar.current.date(bySettingHour: 21, minute: 0, second: 0, of: Date()) ?? Date()
    @State private var preview: TaskPreview?
    @State private var asking = false
    @State private var busy = false

    var body: some View {
        NavigationStack {
            Form {
                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning).listRowBackground(Color.clear)
                }
                Section(lang.s("tasks.instructions")) {
                    TextField(lang.s("tasks.instructions"), text: $words, axis: .vertical)
                        .lineLimit(2...6)
                }
                Section(lang.s("tasks.often")) {
                    Stepper(value: $often, in: 1...(inHours ? 168 : 59 * 60)) {
                        Text(often.formatted(.number.locale(AppLocale.current)))
                    }
                    Picker(lang.s("tasks.often"), selection: $inHours) {
                        Text(lang.s("tasks.oftenMinutes")).tag(false)
                        Text(lang.s("tasks.oftenHours")).tag(true)
                    }
                    .pickerStyle(.segmented)
                }
                Section(lang.s("tasks.how")) {
                    Picker(lang.s("tasks.how"), selection: $mode) {
                        Text(lang.s("tasks.howInstant")).tag(TaskDelivery.instant)
                        Text(lang.s("tasks.howDaily")).tag(TaskDelivery.daily)
                        Text(lang.s("tasks.howEvery")).tag(TaskDelivery.every)
                    }
                    .pickerStyle(.inline)
                    .labelsHidden()
                    if mode == TaskDelivery.daily {
                        DatePicker(lang.s("tasks.at"), selection: $at, displayedComponents: .hourAndMinute)
                    }
                    if mode == TaskDelivery.every {
                        Stepper(value: $hours, in: 1...168) {
                            LabeledContent(lang.s("tasks.hours"), value: hours.formatted(.number.locale(AppLocale.current)))
                        }
                    }
                }
            }
            .navigationTitle(lang.s("tasks.editTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("tasks.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.s("tasks.review")) { review() }
                        .disabled(busy || change.isEmpty)
                }
            }
            .alert(String(format: lang.s("tasks.reviewAsk"), preview?.summary ?? ""), isPresented: $asking) {
                Button(lang.s("tasks.save")) { save() }
                Button(lang.s("tasks.cancel"), role: .cancel) {}
            }
            .onAppear(perform: fill)
        }
    }

    /// What differs from the task as it is: only that is sent.
    var change: TaskChange {
        TaskEditSheet.change(from: task, words: words, minutes: inHours ? often * 60 : often,
                             way: way)
    }

    private var way: TaskDelivery {
        switch mode {
        case TaskDelivery.instant: return TaskDelivery(mode: TaskDelivery.instant)
        case TaskDelivery.daily: return TaskDelivery(mode: TaskDelivery.daily, at: Self.clock(at))
        default: return TaskDelivery(mode: TaskDelivery.every, hours: hours)
        }
    }

    static func change(from task: ScheduledTask, words: String, minutes: Int, way: TaskDelivery) -> TaskChange {
        var c = TaskChange()
        let said = words.trimmingCharacters(in: .whitespacesAndNewlines)
        if said != task.instructions { c.instructions = said }
        if minutes != task.everyMinutes { c.everyMinutes = minutes }
        if way != task.way { c.delivery = way }
        return c
    }

    /// «HH:MM» on the phone's clock, which is the server's for him.
    static func clock(_ date: Date) -> String {
        let parts = Calendar.current.dateComponents([.hour, .minute], from: date)
        return String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0)
    }

    private func fill() {
        words = task.instructions
        inHours = task.everyMinutes % 60 == 0
        often = inHours ? max(task.everyMinutes / 60, 1) : max(task.everyMinutes, 1)
        mode = task.way.mode
        hours = task.way.hours ?? 1
        if let saved = task.way.at, mode == TaskDelivery.daily {
            let hm = saved.split(separator: ":").compactMap { Int($0) }
            if hm.count == 2 {
                at = Calendar.current.date(bySettingHour: hm[0], minute: hm[1], second: 0, of: Date()) ?? at
            }
        }
    }

    private func review() {
        busy = true
        Task {
            preview = await store.preview(change, id: task.id, api: state.api)
            asking = preview != nil
            busy = false
        }
    }

    private func save() {
        var final = change
        final.check = preview?.check
        busy = true
        Task {
            if await store.save(final, id: task.id, api: state.api) { dismiss() }
            busy = false
        }
    }
}
