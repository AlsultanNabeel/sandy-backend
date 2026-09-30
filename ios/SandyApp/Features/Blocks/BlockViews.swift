import SwiftUI

// The three generic screens: one for any list, one for reminders, one for the log.
// What makes "shopping" look like shopping comes from the kinds table, not from code.

/// Short, language-aware date for a row ("اليوم ٥:٣٠ م", "12 Oct").
enum BlockDate {
    static func text(_ iso: String?) -> String? {
        guard let iso, let date = NotificationManager.parseISOOrDay(iso) else { return nil }
        let style = Date.FormatStyle(date: .abbreviated, time: .shortened)
            .locale(AppLocale.current)
        return date.formatted(style)
    }
}

// MARK: - A list

struct ItemsView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject private var kinds = KindsStore.shared
    @StateObject private var store: ItemsStore
    @State private var draft = ""
    private let kind: BlockKind

    init(kind: BlockKind) {
        self.kind = kind
        _store = StateObject(wrappedValue: ItemsStore(list: kind.name))
    }

    var body: some View {
        VStack(spacing: 0) {
            if !store.isHabits {
                Picker("", selection: $store.showDone) {
                    Text(lang.s("blocks.open")).tag(false)
                    Text(lang.s("blocks.done")).tag(true)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.top, Theme.Spacing.sm)
                .onChange(of: store.showDone) { Task { await store.load(api: state.api) } }
            }

            BlockNotices(store: store)

            if store.items.isEmpty && !store.loading {
                Spacer()
                LivelyEmptyState(line: lang.s(store.showDone ? "blocks.emptyDone" : "blocks.emptyList"))
                Spacer()
            } else {
                List {
                    ForEach(store.items) { item in
                        itemRow(item)
                            .blockRow()
                            .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                Button(role: .destructive) { store.delete(api: state.api, item) } label: {
                                    Label(lang.s("blocks.delete"), systemImage: "trash")
                                }
                            }
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }

            if !store.showDone { addBar }
        }
        .navigationTitle((kinds.kind(kind.name, .list) ?? kind).label(lang.lang))
        .task {
            await kinds.load(api: state.api)
            await store.load(api: state.api)
        }
        .refreshable { await store.load(api: state.api) }
    }

    private func itemRow(_ item: ListItem) -> some View {
        let checked = store.isHabits ? store.checkedToday[item.id] != nil : item.done
        return HStack(spacing: Theme.Spacing.md) {
            Button { store.toggle(api: state.api, item) } label: {
                Image(systemName: checked ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: Theme.Icon.lg))
                    .foregroundColor(checked ? Theme.Colors.success : Theme.Colors.accent)
            }
            .buttonStyle(.plain)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.text)
                    .font(Theme.Typography.body)
                    .foregroundColor(item.done ? Theme.Colors.secondaryText : Theme.Colors.primaryText)
                    .strikethrough(item.done)
                if let due = BlockDate.text(item.due) {
                    Label(due, systemImage: "clock")
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
            }
            Spacer(minLength: 0)
            if item.priority == "high" {
                Image(systemName: "flag.fill").foregroundColor(Theme.Colors.warn)
            }
        }
        .sandyCard()
    }

    private var addBar: some View {
        HStack(spacing: Theme.Spacing.sm) {
            TextField(lang.s("blocks.addPlaceholder"), text: $draft)
                .textFieldStyle(.plain)
                .padding(Theme.Spacing.sm)
                .liquidGlass(cornerRadius: Theme.Radius.control)
                .onSubmit(submit)
            Button(action: submit) {
                Image(systemName: "plus.circle.fill")
                    .font(.system(size: Theme.Icon.lg))
                    .foregroundColor(Theme.Colors.accent)
            }
            .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding(Theme.Spacing.md)
    }

    private func submit() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        draft = ""
        Task { await store.add(api: state.api, text: text) }
    }
}

// MARK: - Reminders

struct SchedulesView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject private var kinds = KindsStore.shared
    @ObservedObject private var notifs = NotificationManager.shared
    @StateObject private var store: SchedulesStore
    @State private var adding = false

    init(kind: String = "reminder") {
        _store = StateObject(wrappedValue: SchedulesStore(kind: kind))
    }

    private var title: String {
        store.kind == "reminder" ? lang.s("blocks.reminders")
            : kinds.kindOrBare(store.kind, .schedule).label(lang.lang)
    }

    var body: some View {
        VStack(spacing: 0) {
            BlockNotices(store: store)
            if store.items.isEmpty && !store.loading {
                Spacer()
                LivelyEmptyState(line: lang.s("blocks.emptyReminders"))
                Spacer()
            } else {
                List {
                    ForEach(store.items) { item in
                        row(item)
                            .blockRow()
                            .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                Button(role: .destructive) { store.delete(api: state.api, item) } label: {
                                    Label(lang.s("blocks.delete"), systemImage: "trash")
                                }
                            }
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        }
        .navigationTitle(title)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Button { adding = true } label: { Image(systemName: "plus.circle.fill") }
            }
        }
        .task {
            await kinds.load(api: state.api)
            await store.load(api: state.api)
        }
        .refreshable { await store.load(api: state.api) }
        // A banner button (later / done / delete) changed one while this screen was open.
        .onChange(of: notifs.remindersChanged) { Task { await store.load(api: state.api) } }
        .sheet(isPresented: $adding) {
            AddReminderSheet(title: title, allowRepeat: store.kind == "reminder") { text, date, repeats in
                await store.add(api: state.api, text: text, at: date, recurrence: repeats)
            }
            .environmentObject(lang)
        }
    }

    private func row(_ item: ScheduleItem) -> some View {
        HStack(spacing: Theme.Spacing.md) {
            Image(systemName: (item.recurrence ?? "").isEmpty ? "bell.fill" : "repeat")
                .foregroundColor(Theme.Colors.warn)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.text).font(Theme.Typography.body).foregroundColor(Theme.Colors.primaryText)
                if let when = BlockDate.text(item.fireAt) {
                    Text(when).font(Theme.Typography.caption).foregroundColor(Theme.Colors.secondaryText)
                }
            }
            Spacer(minLength: 0)
        }
        .sandyCard()
    }
}

private struct AddReminderSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let title: String
    let allowRepeat: Bool
    let save: (String, Date, String?) async -> Bool
    @State private var text = ""
    @State private var date = Date().addingTimeInterval(3600)
    @State private var repeats = ""
    @State private var saving = false

    var body: some View {
        NavigationStack {
            Form {
                TextField(lang.s("blocks.reminderPlaceholder"), text: $text)
                DatePicker(lang.s("blocks.when"), selection: $date, in: Date()...)
                if allowRepeat {
                    Picker(lang.s("blocks.repeat"), selection: $repeats) {
                        Text(lang.s("blocks.repeatNone")).tag("")
                        Text(lang.s("blocks.repeatDaily")).tag("daily")
                        Text(lang.s("blocks.repeatWeekly")).tag("weekly")
                        Text(lang.s("blocks.repeatMonthly")).tag("monthly")
                    }
                }
            }
            .navigationTitle(title)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("blocks.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.s("blocks.save")) {
                        saving = true
                        Task {
                            let ok = await save(text.trimmingCharacters(in: .whitespaces), date,
                                                repeats.isEmpty ? nil : repeats)
                            saving = false
                            if ok { dismiss() }
                        }
                    }
                    .disabled(saving || text.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }
}

// MARK: - The log (My life)

struct LogView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject private var kinds = KindsStore.shared
    @StateObject private var store: LogStore
    /// The My Life tab: month strip, your lists and search above the log.
    private let isLife: Bool

    init(kind: String? = nil, isLife: Bool = false) {
        _store = StateObject(wrappedValue: LogStore(kind: kind))
        self.isLife = isLife
    }
    @State private var adding = false
    @State private var summary: String?
    @State private var summarizing = false
    @State private var search = ""

    private var shown: [LogEntry] {
        let q = search.trimmingCharacters(in: .whitespaces)
        return q.isEmpty ? store.entries : store.entries.filter { $0.text.localizedCaseInsensitiveContains(q) }
    }

    private var title: String {
        if isLife { return lang.s("life.title") }
        return store.kind.map { kinds.kindOrBare($0, .log).label(lang.lang) } ?? lang.s("life.title")
    }

    var body: some View {
        List {
            if isLife {
                LifeHeader(entries: store.entries).blockRow()
                filters.listRowInsets(EdgeInsets()).listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            }
            BlockNotices(store: store).blockRow()
            if shown.isEmpty && !store.loading {
                LivelyEmptyState(line: lang.s("blocks.emptyLog")).blockRow()
            }
            ForEach(shown) { entry in
                row(entry)
                    .blockRow()
                    .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                        Button(role: .destructive) { store.delete(api: state.api, entry) } label: {
                            Label(lang.s("blocks.delete"), systemImage: "trash")
                        }
                    }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .searchable(text: $search, prompt: lang.s("blocks.search"))
        .navigationTitle(title)
        .toolbar {
            ToolbarItem(placement: .navigationBarLeading) { summaryMenu }
            ToolbarItem(placement: .navigationBarTrailing) {
                Button { adding = true } label: { Image(systemName: "plus.circle.fill") }
            }
        }
        .task {
            await kinds.load(api: state.api)
            await store.load(api: state.api)
        }
        .refreshable { await store.load(api: state.api) }
        .onChange(of: store.kind) { Task { await store.load(api: state.api) } }
        .sheet(isPresented: $adding) {
            AddEntrySheet(kinds: kinds.logKinds) { kind, text, amount in
                await store.add(api: state.api, kind: kind, text: text, amount: amount)
            }
            .environmentObject(lang)
        }
        .sheet(item: Binding(get: { summary.map(SummaryText.init) }, set: { summary = $0?.text })) { s in
            ScrollView {
                Text(s.text).font(Theme.Typography.body).padding(Theme.Spacing.lg)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .presentationDetents([.medium, .large])
        }
    }

    private var filters: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Theme.Spacing.sm) {
                chip(nil, title: lang.s("blocks.all"), icon: "square.grid.2x2")
                ForEach(kinds.logKinds) { k in chip(k.name, title: k.label(lang.lang), icon: k.icon) }
            }
            .padding(.horizontal, Theme.Spacing.md)
            .padding(.vertical, Theme.Spacing.sm)
        }
    }

    private func chip(_ name: String?, title: String, icon: String) -> some View {
        let on = store.kind == name
        return Button { store.kind = name } label: {
            Label(title, systemImage: icon)
                .font(Theme.Typography.caption)
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.vertical, Theme.Spacing.sm)
                .foregroundColor(on ? Theme.Colors.onAccent : Theme.Colors.primaryText)
                .background(Capsule().fill(on ? Theme.Colors.accent : Theme.Colors.surface.opacity(0.6)))
        }
        .buttonStyle(.plain)
    }

    private var summaryMenu: some View {
        Menu {
            ForEach(["today", "week", "month", "year"], id: \.self) { period in
                Button(lang.s("blocks.period." + period)) { summarize(period) }
            }
        } label: {
            if summarizing {
                ProgressView()
            } else {
                Label(lang.s("blocks.summarize"), systemImage: "sparkles")
                    .labelStyle(.titleAndIcon)
                    .font(Theme.Typography.callout)
            }
        }
        .disabled(summarizing)
    }

    private func summarize(_ period: String) {
        summarizing = true
        Task {
            summary = (try? await state.api.summary(period: period)) ?? lang.s("blocks.errorLoad")
            summarizing = false
        }
    }

    private func row(_ entry: LogEntry) -> some View {
        let k = kinds.kind(entry.kind, .log)
        return HStack(alignment: .top, spacing: Theme.Spacing.md) {
            Image(systemName: k?.icon ?? "circle")
                .foregroundColor(Theme.Colors.accent)
                .frame(width: Theme.Icon.lg)
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.text).font(Theme.Typography.body).foregroundColor(Theme.Colors.primaryText)
                HStack(spacing: Theme.Spacing.sm) {
                    if let k { Text(k.label(lang.lang)) }
                    if let when = BlockDate.text(entry.at) { Text(when) }
                }
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
            }
            Spacer(minLength: 0)
            if let amount = entry.amount {
                Text(amount.formatted(.number.precision(.fractionLength(0...2)).locale(AppLocale.current)))
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.success)
            }
        }
        .sandyCard()
    }
}

private struct SummaryText: Identifiable {
    let text: String
    var id: String { text }
}

private struct AddEntrySheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let kinds: [BlockKind]
    let save: (String, String, Double?) async -> Bool
    @State private var kind = "note"
    @State private var text = ""
    @State private var amount = ""
    @State private var saving = false

    var body: some View {
        NavigationStack {
            Form {
                Picker(lang.s("blocks.kind"), selection: $kind) {
                    ForEach(kinds) { k in Label(k.label(lang.lang), systemImage: k.icon).tag(k.name) }
                }
                TextField(lang.s("blocks.entryPlaceholder"), text: $text, axis: .vertical)
                if kind == "expense" {
                    TextField(lang.s("blocks.amount"), text: $amount).keyboardType(.decimalPad)
                }
            }
            .navigationTitle(lang.s("blocks.newEntry"))
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("blocks.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.s("blocks.save")) {
                        saving = true
                        Task {
                            let value = Double(amount.replacingOccurrences(of: ",", with: "."))
                            let ok = await save(kind, text.trimmingCharacters(in: .whitespaces),
                                                kind == "expense" ? value : nil)
                            saving = false
                            if ok { dismiss() }
                        }
                    }
                    .disabled(saving || text.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }
}

// MARK: - Shared bits

/// Offline banner + Sandy's notice, the same on every block screen.
private struct BlockNotices: View {
    @ObservedObject var store: LoadableStore

    var body: some View {
        if store.offline {
            OfflineBanner().padding(.horizontal, Theme.Spacing.md).padding(.top, Theme.Spacing.sm)
        }
        if !store.notice.isEmpty {
            SandyNotice(store.notice, kind: .gentleWarning)
                .padding(.horizontal, Theme.Spacing.md).padding(.top, Theme.Spacing.sm)
        }
    }
}

extension View {
    /// A clear, separator-less list row with the block screens' insets.
    func blockRow() -> some View {
        listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
            .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                      bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
    }
}
