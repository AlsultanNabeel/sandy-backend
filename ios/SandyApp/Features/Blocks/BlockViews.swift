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
    @StateObject private var open: ItemsStore
    @StateObject private var closed: ItemsStore
    @State private var showDone = false
    @State private var draft = ""
    @State private var editing: ListItem?
    @State private var addingFull = false
    private let kind: BlockKind

    init(kind: BlockKind) {
        self.kind = kind
        _open = StateObject(wrappedValue: ItemsStore(list: kind.name))
        _closed = StateObject(wrappedValue: ItemsStore(list: kind.name, done: true))
    }

    /// The half on screen: open rows, or the done ones.
    private var store: ItemsStore { showDone ? closed : open }

    var body: some View {
        VStack(spacing: 0) {
            if !store.isHabits {
                Picker("", selection: $showDone) {
                    Text(lang.s("blocks.open")).tag(false)
                    Text(lang.s("blocks.done")).tag(true)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.top, Theme.Spacing.sm)
                .onChange(of: showDone) { Task { await store.load(api: state.api) } }
            }

            BlockNotices(store: store)
            if store.isHabits {
                HabitProgressLine(habits: store)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, Theme.Spacing.md)
                    .padding(.top, Theme.Spacing.sm)
                    .task { await LifeStatsStore.shared.load(api: state.api) }
            }

            if store.items.isEmpty && store.loading && !store.hasSnapshot {
                // First open, nothing on the phone yet: the rows' shapes until they come.
                SkeletonList().padding(Theme.Spacing.md)
                Spacer()
            } else if store.items.isEmpty && !store.loading {
                Spacer()
                LivelyEmptyState(line: lang.s(showDone ? "blocks.emptyDone" : "blocks.emptyList"))
                Spacer()
            } else {
                List {
                    ForEach(store.ordered) { item in
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
                .animation(Animation.spring(response: 0.45, dampingFraction: 0.85).reduced, value: store.ordered.map(\.id))
            }

            if !showDone { addBar }
        }
        .navigationTitle(title)
        .sheet(item: $editing) { item in
            ItemEditSheet(title: title, item: item, isHabit: store.isHabits,
                          save: { store.update(api: state.api, item, $0) },
                          delete: { store.delete(api: state.api, item) })
                .environmentObject(lang)
        }
        .sheet(isPresented: $addingFull) {
            ItemEditSheet(title: title, item: nil, draft: draft, isHabit: store.isHabits,
                          save: { new in
                              draft = ""
                              Task { await store.add(api: state.api, new) }
                          })
                .environmentObject(lang)
        }
        .task {
            await kinds.load(api: state.api)
            await store.load(api: state.api)
        }
        .refreshable { await store.load(api: state.api) }
        .onReceive(NotificationCenter.default.publisher(for: .sandyBlocksChanged)) { _ in
            Task { await store.load(api: state.api) }
        }
    }

    private var title: String { (kinds.kind(kind.name, .list) ?? kind).label(lang.lang) }


    private func itemRow(_ item: ListItem) -> some View {
        let checked = store.isHabits ? store.checkedToday[item.id] != nil : item.done
        return HStack(spacing: Theme.Spacing.md) {
            Button { store.toggle(api: state.api, item) } label: {
                Image(systemName: checked ? "checkmark.circle.fill" : "circle")
                    .scaledFont(Theme.Icon.lg)
                    .foregroundColor(checked ? Theme.Colors.success : Theme.Colors.accent)
            }
            .buttonStyle(.plain)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.text)
                    .font(Theme.Typography.body)
                    .foregroundColor(checked ? Theme.Colors.secondaryText : Theme.Colors.primaryText)
                    .strikethrough(item.done)
                if let due = BlockDate.text(item.due) {
                    Label(due, systemImage: item.repeatRule == nil ? "clock" : "repeat")
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
                if store.isHabits, let plan = HabitPlan.text(item, lang: lang) {
                    Label(plan, systemImage: "calendar")
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
            }
            Spacer(minLength: 0)
            if item.priority == "high" {
                Image(systemName: "flag.fill").foregroundColor(Theme.Colors.warn)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { editing = item }
        .opacity(store.isHabits && checked ? 0.6 : 1)
        .sandyCard()
        .rowAccessibility(label: A11yText.item(item),
                          value: lang.s(store.isHabits ? (checked ? "a11y.keptToday" : "a11y.notKeptToday")
                                                       : (checked ? "a11y.done" : "a11y.notDone")),
                          hint: lang.s("a11y.rowHint"), open: { editing = item },
                          actions: [
                              (lang.s(checked ? "a11y.markOpen" : "a11y.markDone"),
                               { store.toggle(api: state.api, item) }),
                              (lang.s("a11y.delete"), { store.delete(api: state.api, item) }),
                          ])
    }

    private var addBar: some View {
        HStack(spacing: Theme.Spacing.sm) {
            if !store.isHabits {
                // The full sheet: a time and a flag along with the text.
                Button { addingFull = true } label: {
                    Image(systemName: "calendar.badge.plus")
                        .scaledFont(Theme.Icon.md)
                        .foregroundColor(Theme.Colors.accent)
                }
                .accessibilityLabel(lang.s("blocks.addWithTime"))
            }
            TextField(lang.s("blocks.addPlaceholder"), text: $draft)
                .textFieldStyle(.plain)
                .padding(Theme.Spacing.sm)
                .liquidGlass(cornerRadius: Theme.Radius.control)
                .onSubmit(submit)
            Button(action: submit) {
                Image(systemName: "plus.circle.fill")
                    .accessibilityLabel(LanguageManager.shared.s("a11y.add"))
                    .scaledFont(Theme.Icon.lg)
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
    @State private var editing: ScheduleItem?

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
            if store.kind == "reminder" {
                // Reminders ring as notifications: say so when they are off.
                PermissionCard(kind: .notifications)
                    .padding(.horizontal, Theme.Spacing.md).padding(.top, Theme.Spacing.sm)
                    .task { await Permissions.shared.refresh() }
            }
            if store.items.isEmpty && store.loading && !store.hasSnapshot {
                SkeletonList().padding(Theme.Spacing.md)
                Spacer()
            } else if store.items.isEmpty && !store.loading {
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
                            .swipeActions(edge: .leading, allowsFullSwipe: true) {
                                if store.kind == "reminder" && (item.recurrence ?? "").isEmpty {
                                    Button { store.complete(api: state.api, item) } label: {
                                        Label(lang.s("blocks.markDone"), systemImage: "checkmark")
                                    }
                                    .tint(Theme.Colors.success)
                                }
                            }
                            .contextMenu { ReminderActions(store: store, item: item) { editing = item } }
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
                    .accessibilityLabel(LanguageManager.shared.s("a11y.add"))
                    .accessibilityLabel(LanguageManager.shared.s("a11y.add"))
            }
        }
        .task {
            await kinds.load(api: state.api)
            await store.load(api: state.api)
        }
        .refreshable { await store.load(api: state.api) }
        .onReceive(NotificationCenter.default.publisher(for: .sandyBlocksChanged)) { _ in
            Task { await store.load(api: state.api) }
        }
        // A banner button (later / done / delete) changed one while this screen was open.
        .onChange(of: notifs.remindersChanged) { Task { await store.load(api: state.api) } }
        .sheet(isPresented: $adding) {
            ReminderEditSheet(title: title, allowRepeat: store.kind == "reminder") { text, date, repeats in
                await store.add(api: state.api, text: text, at: date, recurrence: repeats)
            }
            .environmentObject(lang)
        }
        .sheet(item: $editing) { item in
            ReminderEditSheet(title: title, item: item, allowRepeat: store.kind == "reminder",
                              save: { text, date, repeats in
                                  await store.update(api: state.api, item, text: text, at: date,
                                                     recurrence: repeats)
                              },
                              delete: { store.delete(api: state.api, item) })
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
        .contentShape(Rectangle())
        .onTapGesture { editing = item }
        .sandyCard()
        .rowAccessibility(label: [item.text, BlockDate.text(item.fireAt) ?? "",
                                  (item.recurrence ?? "").isEmpty ? "" : lang.s("a11y.repeats")]
                                    .filter { !$0.isEmpty }.joined(separator: lang.s("common.listSeparator")),
                          hint: lang.s("a11y.rowHint"), open: { editing = item },
                          actions: A11yText.reminderActions(item, store: store, api: state.api))
    }
}

/// Long-press menu on a reminder: later, done, edit, delete.
struct ReminderActions: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var store: SchedulesStore
    let item: ScheduleItem
    let edit: () -> Void

    var body: some View {
        Button { store.snooze(api: state.api, item, minutes: 15) } label: {
            Label(lang.s("blocks.quick.15"), systemImage: "clock.arrow.circlepath")
        }
        Button { store.snooze(api: state.api, item, minutes: 60) } label: {
            Label(lang.s("blocks.quick.hour"), systemImage: "clock.arrow.circlepath")
        }
        if (item.recurrence ?? "").isEmpty {
            Button { store.complete(api: state.api, item) } label: {
                Label(lang.s("blocks.markDone"), systemImage: "checkmark")
            }
        }
        Button(action: edit) { Label(lang.s("blocks.edit"), systemImage: "pencil") }
        Button(role: .destructive) { store.delete(api: state.api, item) } label: {
            Label(lang.s("blocks.delete"), systemImage: "trash")
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
    @State private var editing: LogEntry?
    @State private var day: Date?
    @State private var summary: String?
    @State private var summarizing = false
    @State private var search = ""
    @ObservedObject private var lifeStats = LifeStatsStore.shared
    @State private var showSpending = false
    /// What the server found for the search or the picked day, over the whole log;
    /// nil while there is no query, or offline (then the rows on the phone are filtered).
    @State private var found: [LogEntry]?

    private var query: String { search.trimmingCharacters(in: .whitespaces) }

    private var shown: [LogEntry] {
        if let found {
            // The phone's copy of a row wins: an edit made since shows at once.
            return found.compactMap { hit in store.entries.first { $0.id == hit.id } ?? hit }
        }
        var rows = query.isEmpty ? store.entries
                                 : store.entries.filter { $0.text.localizedCaseInsensitiveContains(query) }
        if let day {
            let cal = Calendar.current
            rows = rows.filter {
                guard let at = NotificationManager.parseISO($0.at ?? "") else { return false }
                return cal.isDate(at, inSameDayAs: day)
            }
        }
        return rows
    }

    /// Asks the server for the search and the picked day, a moment after typing stops.
    private func lookUp() async {
        guard !query.isEmpty || day != nil else { found = nil; return }
        try? await Task.sleep(for: .milliseconds(350))
        guard !Task.isCancelled else { return }
        let start = day.map { Calendar.current.startOfDay(for: $0) }
        found = try? await state.api.entries(kind: store.kind, limit: 200,
                                             q: query.isEmpty ? nil : query, since: start,
                                             until: start.map { $0.addingTimeInterval(86_400 - 1) })
    }

    private var title: String {
        if isLife { return lang.s("life.title") }
        return store.kind.map { kinds.kindOrBare($0, .log).label(lang.lang) } ?? lang.s("life.title")
    }

    var body: some View {
        List {
            if isLife {
                LifeHeader(stats: lifeStats.stats, day: $day) { showSpending = true }.blockRow()
                filters.listRowInsets(EdgeInsets()).listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            }
            BlockNotices(store: store).blockRow()
            if shown.isEmpty && store.loading && !store.hasSnapshot {
                SkeletonList().blockRow()
            } else if shown.isEmpty && !store.loading {
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
        // Always shown: a search field that slides in on the same pull as the refresh
        // made the list jump.
        .searchable(text: $search, placement: .navigationBarDrawer(displayMode: .always),
                    prompt: lang.s("blocks.search"))
        .sheet(isPresented: $showSpending) { SpendingSheet(stats: lifeStats.stats) }
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
            if isLife { await lifeStats.load(api: state.api) }
        }
        .refreshable {
            async let rows: Void = store.load(api: state.api)
            async let numbers: Void = isLife ? lifeStats.load(api: state.api) : ()
            _ = await (rows, numbers)
        }
        .onChange(of: store.kind) { Task { await store.load(api: state.api) } }
        .onReceive(NotificationCenter.default.publisher(for: .sandyBlocksChanged)) { _ in
            Task { await store.load(api: state.api) }
        }
        .task(id: "\(query)|\(day?.timeIntervalSince1970 ?? 0)|\(store.kind ?? "")") { await lookUp() }
        .sheet(isPresented: $adding) {
            EntryEditSheet(kinds: kinds.logKinds, kind: store.kind ?? "note") { kind, text, amount, category, at in
                await store.add(api: state.api, kind: kind, text: text, amount: amount, category: category, at: at)
            }
            .environmentObject(lang)
        }
        .sheet(item: $editing) { entry in
            EntryEditSheet(kinds: kinds.logKinds, entry: entry,
                           save: { _, text, amount, category, at in
                               store.update(api: state.api, entry, text: text, amount: amount,
                                            category: category, at: at)
                               return true
                           },
                           delete: { store.delete(api: state.api, entry) })
            .environmentObject(lang)
        }
        .sheet(item: Binding(get: { summary.map(SummaryText.init) }, set: { summary = $0?.text })) { s in
            SummarySheet(text: s.text).environmentObject(lang)
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
                LoadingDots()
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
            Image(systemName: entry.kind == "expense" ? ExpenseCategory.icon(entry.category) : k?.icon ?? "circle")
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
        .contentShape(Rectangle())
        .onTapGesture { editing = entry }
        .sandyCard()
        .rowAccessibility(label: [k?.label(lang.lang) ?? "", entry.text,
                                  entry.amount.map { AppLocale.number($0) } ?? "",
                                  BlockDate.text(entry.at) ?? ""]
                                    .filter { !$0.isEmpty }.joined(separator: lang.s("common.listSeparator")),
                          hint: lang.s("a11y.rowHint"), open: { editing = entry },
                          actions: [(lang.s("a11y.delete"), { store.delete(api: state.api, entry) })])
    }
}

private struct SummaryText: Identifiable {
    let text: String
    var id: String { text }
}

/// A summary Sandy wrote, as a card with her face on it.
private struct SummarySheet: View {
    @EnvironmentObject var lang: LanguageManager
    let text: String

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                HStack(spacing: Theme.Spacing.sm) {
                    SandyAvatar(size: 36, mood: .happy)
                    Text(lang.s("blocks.summaryTitle"))
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.secondaryText)
                    Spacer()
                    ShareLink(item: text) { Image(systemName: "square.and.arrow.up") }
                        .foregroundColor(Theme.Colors.accent)
                }
                Text(text)
                    .scaledFont(17, design: .rounded)
                    .lineSpacing(6)
                    .foregroundColor(Theme.Colors.primaryText)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(Theme.Spacing.lg)
        }
        .background(SandyBackground())
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}

/// «🔥 سلسلة ٥ أيام · ١٢ يوم التزام»: days on which every habit due was kept.
struct HabitProgressLine: View {
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var habits: ItemsStore
    @ObservedObject private var stats = LifeStatsStore.shared

    var body: some View {
        let progress = stats.stats.habitProgress ?? HabitProgress(baseCommitted: 0, baseStreak: 0)
        let done = habits.todayComplete
        let streak = progress.streak(todayComplete: done)
        let committed = progress.committed(todayComplete: done)
        HStack(spacing: Theme.Spacing.sm) {
            Label(String(format: lang.s("blocks.habitStreak"), AppLocale.number(streak)), systemImage: "flame.fill")
                .foregroundColor(streak > 0 ? Theme.Colors.warn : Theme.Colors.tertiaryText)
            Text("·").foregroundColor(Theme.Colors.tertiaryText)
            Text(String(format: lang.s("blocks.habitCommitted"), AppLocale.number(committed)))
                .foregroundColor(Theme.Colors.secondaryText)
        }
        .font(Theme.Typography.caption.weight(.semibold))
        .contentTransition(.numericText())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(String(format: lang.s("a11y.habitProgress"),
                                   AppLocale.number(streak), AppLocale.number(committed)))
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

/// What the screen reader says for list rows, shared by the lists and Today.
@MainActor
enum A11yText {
    static func item(_ item: ListItem) -> String {
        let lang = LanguageManager.shared
        var parts = [item.text]
        if let due = BlockDate.text(item.due) { parts.append(due) }
        if item.repeatRule != nil { parts.append(lang.s("a11y.repeats")) }
        if item.priority == "high" { parts.append(lang.s("a11y.important")) }
        return parts.joined(separator: lang.s("common.listSeparator"))
    }

    static func reminderActions(_ item: ScheduleItem, store: SchedulesStore,
                                api: APIClient) -> [(name: String, run: () -> Void)] {
        let lang = LanguageManager.shared
        var out: [(name: String, run: () -> Void)] = [
            (lang.s("a11y.snooze15"), { store.snooze(api: api, item, minutes: 15) }),
            (lang.s("a11y.snoozeHour"), { store.snooze(api: api, item, minutes: 60) }),
        ]
        if (item.recurrence ?? "").isEmpty {
            out.append((lang.s("a11y.markDone"), { store.complete(api: api, item) }))
        }
        out.append((lang.s("a11y.delete"), { store.delete(api: api, item) }))
        return out
    }
}
