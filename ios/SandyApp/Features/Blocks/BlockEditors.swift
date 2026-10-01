import SwiftUI

// The edit sheets every screen shares: tap a task, habit, reminder or log row anywhere
// and the same sheet opens. A sheet with no row adds a new one.

// MARK: - A list item (task, habit, shopping…)

struct ItemEditSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let title: String
    let item: ListItem?
    let isHabit: Bool
    let save: (String, Date?, Bool) -> Void
    var delete: (() -> Void)?

    @State private var text: String
    @State private var timed: Bool
    @State private var due: Date
    @State private var important: Bool
    @State private var confirmDelete = false

    init(title: String, item: ListItem?, draft: String = "", isHabit: Bool,
         save: @escaping (String, Date?, Bool) -> Void, delete: (() -> Void)? = nil) {
        self.title = title
        self.item = item
        self.isHabit = isHabit
        self.save = save
        self.delete = delete
        let date = NotificationManager.parseISOOrDay(item?.due ?? "")
        _text = State(initialValue: item?.text ?? draft)
        _timed = State(initialValue: date != nil)
        _due = State(initialValue: date ?? EditTimes.nextRoundHour())
        _important = State(initialValue: item?.priority == "high")
    }

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        NavigationStack {
            Form {
                TextField(lang.s("blocks.itemPlaceholder"), text: $text, axis: .vertical)
                if !isHabit {
                    Section {
                        Toggle(lang.s("blocks.hasTime"), isOn: $timed.animation())
                        if timed {
                            QuickTimes(date: $due)
                            DatePicker(lang.s("blocks.when"), selection: $due)
                        }
                        Toggle(lang.s("blocks.important"), isOn: $important)
                    }
                }
                if let delete {
                    Section {
                        Button(lang.s("blocks.delete"), role: .destructive) { confirmDelete = true }
                            .confirmationDialog(lang.s("blocks.deleteAsk"), isPresented: $confirmDelete,
                                                titleVisibility: .visible) {
                                Button(lang.s("blocks.delete"), role: .destructive) { delete(); dismiss() }
                            }
                    }
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("blocks.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.s("blocks.save")) {
                        save(trimmed, timed && !isHabit ? due : nil, important)
                        dismiss()
                    }
                    .disabled(trimmed.isEmpty)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

// MARK: - A reminder (add or edit)

struct ReminderEditSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let title: String
    let item: ScheduleItem?
    let allowRepeat: Bool
    let save: (String, Date, String?) async -> Bool
    var delete: (() -> Void)?

    @State private var text: String
    @State private var date: Date
    @State private var repeats: String
    @State private var saving = false
    @State private var confirmDelete = false

    init(title: String, item: ScheduleItem? = nil, allowRepeat: Bool,
         save: @escaping (String, Date, String?) async -> Bool, delete: (() -> Void)? = nil) {
        self.title = title
        self.item = item
        self.allowRepeat = allowRepeat
        self.save = save
        self.delete = delete
        let at = item.flatMap { NotificationManager.parseISO($0.fireAt) }
        _text = State(initialValue: item?.text ?? "")
        _date = State(initialValue: at.map { max($0, Date().addingTimeInterval(60)) } ?? EditTimes.nextRoundHour())
        _repeats = State(initialValue: EditTimes.repeatName(item?.recurrence))
    }

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        NavigationStack {
            Form {
                TextField(lang.s("blocks.reminderPlaceholder"), text: $text, axis: .vertical)
                Section {
                    QuickTimes(date: $date)
                    DatePicker(lang.s("blocks.when"), selection: $date, in: Date()...)
                    if allowRepeat {
                        Picker(lang.s("blocks.repeat"), selection: $repeats) {
                            Text(lang.s("blocks.repeatNone")).tag("")
                            Text(lang.s("blocks.repeatDaily")).tag("daily")
                            Text(lang.s("blocks.repeatWeekly")).tag("weekly")
                            Text(lang.s("blocks.repeatMonthly")).tag("monthly")
                            Text(lang.s("blocks.repeatYearly")).tag("yearly")
                        }
                    }
                }
                if let delete {
                    Section {
                        Button(lang.s("blocks.delete"), role: .destructive) { confirmDelete = true }
                            .confirmationDialog(lang.s("blocks.deleteAsk"), isPresented: $confirmDelete,
                                                titleVisibility: .visible) {
                                Button(lang.s("blocks.delete"), role: .destructive) { delete(); dismiss() }
                            }
                    }
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("blocks.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.s("blocks.save")) {
                        saving = true
                        Task {
                            let ok = await save(trimmed, date, repeats.isEmpty ? nil : repeats)
                            saving = false
                            if ok { dismiss() }
                        }
                    }
                    .disabled(saving || trimmed.isEmpty)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

// MARK: - A log row (add or edit)

struct EntryEditSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let kinds: [BlockKind]
    let entry: LogEntry?
    let save: (String, String, Double?, Date) async -> Bool
    var delete: (() -> Void)?

    @State private var kind: String
    @State private var text: String
    @State private var amount: String
    @State private var at: Date
    @State private var saving = false
    @State private var confirmDelete = false

    init(kinds: [BlockKind], entry: LogEntry? = nil, kind: String = "note",
         save: @escaping (String, String, Double?, Date) async -> Bool, delete: (() -> Void)? = nil) {
        self.kinds = kinds
        self.entry = entry
        self.save = save
        self.delete = delete
        _kind = State(initialValue: entry?.kind ?? kind)
        _text = State(initialValue: entry?.text ?? "")
        _amount = State(initialValue: entry?.amount.map {
            $0.formatted(.number.precision(.fractionLength(0...2)).grouping(.never)
                .locale(Locale(identifier: "en_US_POSIX")))
        } ?? "")
        _at = State(initialValue: NotificationManager.parseISO(entry?.at ?? "") ?? Date())
    }

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    /// Arabic digits and a comma both read as a number.
    private var value: Double? {
        let latin = amount.map { ch -> Character in
            if let d = ch.wholeNumberValue, !ch.isASCII { return Character(String(d)) }
            return ch == "٫" || ch == "," ? "." : ch
        }
        return Double(String(latin))
    }

    var body: some View {
        NavigationStack {
            Form {
                if entry == nil {
                    Picker(lang.s("blocks.kind"), selection: $kind) {
                        ForEach(kinds) { k in Label(k.label(lang.lang), systemImage: k.icon).tag(k.name) }
                    }
                }
                TextField(lang.s("blocks.entryPlaceholder"), text: $text, axis: .vertical)
                if kind == "expense" {
                    TextField(lang.s("blocks.amount"), text: $amount).keyboardType(.decimalPad)
                }
                DatePicker(lang.s("blocks.when"), selection: $at, in: ...Date())
                if let delete {
                    Section {
                        Button(lang.s("blocks.delete"), role: .destructive) { confirmDelete = true }
                            .confirmationDialog(lang.s("blocks.deleteAsk"), isPresented: $confirmDelete,
                                                titleVisibility: .visible) {
                                Button(lang.s("blocks.delete"), role: .destructive) { delete(); dismiss() }
                            }
                    }
                }
            }
            .navigationTitle(lang.s(entry == nil ? "blocks.newEntry" : "blocks.editEntry"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("blocks.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.s("blocks.save")) {
                        saving = true
                        Task {
                            let ok = await save(kind, trimmed, kind == "expense" ? value : nil, at)
                            saving = false
                            if ok { dismiss() }
                        }
                    }
                    .disabled(saving || trimmed.isEmpty)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

// MARK: - Shared bits

enum EditTimes {
    /// The next whole hour at least half an hour away: a sensible first guess.
    static func nextRoundHour(from now: Date = Date()) -> Date {
        let cal = Calendar.current
        let later = now.addingTimeInterval(30 * 60)
        let hour = cal.dateInterval(of: .hour, for: later)?.start ?? later
        return hour.addingTimeInterval(3600)
    }

    /// The picker's name for a stored RRULE ("FREQ=WEEKLY" → "weekly").
    static func repeatName(_ rule: String?) -> String {
        let r = (rule ?? "").uppercased()
        for name in ["daily", "weekly", "monthly", "yearly"] where r.contains("FREQ=" + name.uppercased()) {
            return name
        }
        return ""
    }

    /// Today at `hour`, or tomorrow when that has passed.
    static func next(hour: Int, now: Date = Date()) -> Date {
        let cal = Calendar.current
        let today = cal.date(bySettingHour: hour, minute: 0, second: 0, of: now) ?? now
        return today > now ? today : cal.date(byAdding: .day, value: 1, to: today) ?? today
    }

    static func tomorrow(hour: Int, now: Date = Date()) -> Date {
        let cal = Calendar.current
        let day = cal.date(byAdding: .day, value: 1, to: now) ?? now
        return cal.date(bySettingHour: hour, minute: 0, second: 0, of: day) ?? day
    }
}

/// One-tap times: in a quarter hour, in an hour, tonight, tomorrow morning.
struct QuickTimes: View {
    @EnvironmentObject var lang: LanguageManager
    @Binding var date: Date

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Theme.Spacing.sm) {
                chip("blocks.quick.15") { Date().addingTimeInterval(15 * 60) }
                chip("blocks.quick.hour") { Date().addingTimeInterval(3600) }
                chip("blocks.quick.tonight") { EditTimes.next(hour: 21) }
                chip("blocks.quick.morning") { EditTimes.tomorrow(hour: 9) }
            }
        }
    }

    private func chip(_ key: String, _ when: @escaping () -> Date) -> some View {
        Button { withAnimation { date = when() } } label: {
            Text(lang.s(key))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.accent)
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.vertical, 6)
                .background(Capsule().stroke(Theme.Colors.accent.opacity(0.5), lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

/// «خلّصت … · تراجع» for a few seconds after ticking something done.
struct UndoToast: View {
    @EnvironmentObject var lang: LanguageManager
    let text: String
    let undo: () -> Void
    let close: () -> Void

    var body: some View {
        HStack(spacing: Theme.Spacing.md) {
            Image(systemName: "checkmark.circle.fill").foregroundColor(Theme.Colors.success)
            Text(String(format: lang.s("blocks.doneToast"), text))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.primaryText)
                .lineLimit(1)
            Spacer(minLength: 0)
            Button(lang.s("blocks.undo"), action: undo)
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.accent)
        }
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.vertical, 12)
        .liquidGlass(cornerRadius: 18)
        .padding(.horizontal, Theme.Spacing.md)
        .transition(.move(edge: .bottom).combined(with: .opacity))
        .task(id: text) {
            try? await Task.sleep(for: .seconds(4))
            close()
        }
    }
}

extension View {
    /// The undo toast at the bottom while `store.justDone` is set.
    func undoToast(_ store: ItemsStore, api: APIClient, bottom: CGFloat = 0) -> some View {
        overlay(alignment: .bottom) {
            if let item = store.justDone {
                UndoToast(text: item.text,
                          undo: { withAnimation { store.undoDone(api: api) } },
                          close: { withAnimation { if store.justDone?.id == item.id { store.justDone = nil } } })
                    .padding(.bottom, bottom)
            }
        }
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: store.justDone?.id)
    }
}
