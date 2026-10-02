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
    let save: (ItemDraft) -> Void
    var delete: (() -> Void)?

    @State private var text: String
    @State private var timed: Bool
    @State private var due: Date
    @State private var important: Bool
    @State private var repeats: String
    @State private var days: Set<Int>
    @State private var reminds: Bool
    @State private var time: Date
    @State private var confirmDelete = false

    init(title: String, item: ListItem?, draft: String = "", isHabit: Bool,
         save: @escaping (ItemDraft) -> Void, delete: (() -> Void)? = nil) {
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
        _repeats = State(initialValue: item?.repeatRule ?? "")
        _days = State(initialValue: Set(item?.habitDays ?? []))
        _reminds = State(initialValue: item?.habitTime != nil)
        _time = State(initialValue: EditTimes.clock(item?.habitTime) ?? EditTimes.next(hour: 20))
    }

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    private var draft: ItemDraft {
        if isHabit {
            return ItemDraft(text: trimmed, due: nil, important: important, repeatRule: nil,
                             days: days.sorted(), time: reminds ? EditTimes.clockText(time) : nil)
        }
        return ItemDraft(text: trimmed, due: timed ? due : nil, important: important,
                         repeatRule: timed && !repeats.isEmpty ? repeats : nil)
    }

    var body: some View {
        NavigationStack {
            Form {
                TextField(lang.s("blocks.itemPlaceholder"), text: $text, axis: .vertical)
                if isHabit {
                    Section(lang.s("blocks.habitDays")) {
                        WeekdayPicker(days: $days)
                        Toggle(lang.s("blocks.remindMe"), isOn: $reminds.animation())
                        if reminds {
                            DatePicker(lang.s("blocks.when"), selection: $time, displayedComponents: .hourAndMinute)
                        }
                    }
                } else {
                    Section {
                        Toggle(lang.s("blocks.hasTime"), isOn: $timed.animation())
                        if timed {
                            QuickTimes(date: $due)
                            DatePicker(lang.s("blocks.when"), selection: $due)
                            Picker(lang.s("blocks.repeat"), selection: $repeats) {
                                Text(lang.s("blocks.repeatNone")).tag("")
                                Text(lang.s("blocks.repeatDaily")).tag("daily")
                                Text(lang.s("blocks.repeatWeekly")).tag("weekly")
                                Text(lang.s("blocks.repeatMonthly")).tag("monthly")
                            }
                        }
                    }
                }
                Section { Toggle(lang.s("blocks.important"), isOn: $important) }
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
                        save(draft)
                        dismiss()
                    }
                    .disabled(trimmed.isEmpty)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

/// Seven round toggles, Sunday first; none on means every day.
struct WeekdayPicker: View {
    @Binding var days: Set<Int>

    private var symbols: [String] {
        var cal = Calendar(identifier: .gregorian)
        cal.locale = AppLocale.current
        return cal.veryShortWeekdaySymbols
    }

    var body: some View {
        HStack(spacing: 6) {
            ForEach(1...7, id: \.self) { day in
                let on = days.contains(day)
                Button {
                    if on { days.remove(day) } else { days.insert(day) }
                } label: {
                    Text(symbols[day - 1])
                        .font(.system(size: 14, weight: .semibold, design: .rounded))
                        .frame(width: 34, height: 34)
                        .foregroundColor(on ? Theme.Colors.onAccent : Theme.Colors.primaryText)
                        .background(Circle().fill(on ? Theme.Colors.accent : Theme.Colors.surface.opacity(0.6)))
                }
                .buttonStyle(.plain)
            }
        }
        .frame(maxWidth: .infinity)
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
    /// (kind, text, amount, category, time)
    let save: (String, String, Double?, String?, Date) async -> Bool
    var delete: (() -> Void)?

    @State private var kind: String
    @State private var text: String
    @State private var amount: String
    @State private var category: String
    @State private var at: Date
    @State private var saving = false
    @State private var confirmDelete = false

    init(kinds: [BlockKind], entry: LogEntry? = nil, kind: String = "note",
         save: @escaping (String, String, Double?, String?, Date) async -> Bool, delete: (() -> Void)? = nil) {
        self.kinds = kinds
        self.entry = entry
        self.save = save
        self.delete = delete
        _kind = State(initialValue: entry?.kind ?? kind)
        _text = State(initialValue: entry?.text ?? "")
        _category = State(initialValue: entry?.category ?? "food")
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
                    CategoryPicker(selection: $category)
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
                            let ok = await save(kind, trimmed, kind == "expense" ? value : nil,
                                                kind == "expense" ? category : nil, at)
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

    /// "18:30" as today at that time.
    static func clock(_ text: String?) -> Date? {
        let parts = (text ?? "").split(separator: ":").compactMap { Int($0) }
        guard parts.count == 2 else { return nil }
        return Calendar.current.date(bySettingHour: parts[0], minute: parts[1], second: 0, of: Date())
    }

    static func clockText(_ date: Date) -> String {
        let c = Calendar.current.dateComponents([.hour, .minute], from: date)
        return String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0)
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

/// A habit's days and time in a few words («أحد، ثلاثاء · ٦:٣٠ م»); nil for every day, no time.
enum HabitPlan {
    @MainActor
    static func text(_ habit: ListItem, lang: LanguageManager) -> String? {
        var parts: [String] = []
        if !habit.habitDays.isEmpty {
            var cal = Calendar(identifier: .gregorian)
            cal.locale = AppLocale.current
            let names = cal.shortWeekdaySymbols
            parts.append(habit.habitDays.sorted().compactMap { (1...7).contains($0) ? names[$0 - 1] : nil }
                .joined(separator: lang.lang == .ar ? "، " : ", "))
        }
        if let at = EditTimes.clock(habit.habitTime) {
            parts.append(at.formatted(Date.FormatStyle(date: .omitted, time: .shortened).locale(AppLocale.current)))
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}

/// The expense categories, with their icons; the server keeps the name.
enum ExpenseCategory {
    static let all: [(name: String, icon: String)] = [
        ("food", "fork.knife"), ("transport", "car.fill"), ("shopping", "bag.fill"),
        ("bills", "doc.text.fill"), ("fun", "gamecontroller.fill"), ("health", "cross.case.fill"),
        ("other", "square.grid.2x2.fill"),
    ]

    static func icon(_ name: String) -> String {
        all.first { $0.name == name }?.icon ?? "square.grid.2x2.fill"
    }
}

struct CategoryPicker: View {
    @EnvironmentObject var lang: LanguageManager
    @Binding var selection: String

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Theme.Spacing.sm) {
                ForEach(ExpenseCategory.all, id: \.name) { cat in
                    let on = selection == cat.name
                    Button { selection = cat.name } label: {
                        Label(lang.s("blocks.cat." + cat.name), systemImage: cat.icon)
                            .font(Theme.Typography.caption)
                            .padding(.horizontal, Theme.Spacing.md)
                            .padding(.vertical, 7)
                            .foregroundColor(on ? Theme.Colors.onAccent : Theme.Colors.primaryText)
                            .background(Capsule().fill(on ? Theme.Colors.accent : Theme.Colors.surface.opacity(0.6)))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}
