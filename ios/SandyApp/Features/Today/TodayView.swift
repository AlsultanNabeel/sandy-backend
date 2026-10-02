import SwiftUI

/// اليوم — one screen that says what today holds and lets you act on it in place:
/// a sentence about your day, the ask bar, the rest of the day as a ribbon, what can
/// happen any time, and today's habits as rings. Nothing here needs another screen.
struct TodayView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var tasks = ItemsStore(list: "tasks")
    @StateObject private var habits = ItemsStore(list: "habits")
    @StateObject private var reminders = SchedulesStore()
    @StateObject private var nudge = DailyNudgeStore()
    @StateObject private var weather = WeatherStore()
    @StateObject private var expenses = LogStore(kind: "expense")
    @State private var showProfile = false
    @Environment(\.dynamicTypeSize) private var typeSize
    @State private var editingTask: ListItem?
    @State private var editingHabit: ListItem?
    @State private var editingReminder: ScheduleItem?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                header
                Text(briefing)
                    .scaledFont(26, weight: .bold, design: .rounded, relativeTo: .largeTitle)
                    .foregroundColor(Theme.Colors.primaryText)
                    .fixedSize(horizontal: false, vertical: true)
                    .contentTransition(.opacity)
                AskBar { await reload() }
                if nudge.nudge != nil && !nudge.dismissed { DailyNudgeCard(store: nudge) }
                section("today.restOfDay") {
                    if tasks.loading && !tasks.hasSnapshot && moments.isEmpty {
                        SkeletonList(rows: 3)
                    } else {
                    DayRibbon(moments: moments,
                              onDone: { source in
                                  switch source {
                                  case .task(let t): withAnimation { tasks.toggle(api: state.api, t) }
                                  case .reminder(let r): withAnimation { reminders.complete(api: state.api, r) }
                                  }
                              },
                              onOpen: { source in
                                  switch source {
                                  case .task(let t): editingTask = t
                                  case .reminder(let r): editingReminder = r
                                  }
                              },
                              onSnooze: { r, minutes in
                                  withAnimation { reminders.snooze(api: state.api, r, minutes: minutes) }
                              },
                              onDelete: { source in
                                  switch source {
                                  case .task(let t): withAnimation { tasks.delete(api: state.api, t) }
                                  case .reminder(let r): withAnimation { reminders.delete(api: state.api, r) }
                                  }
                              })
                    }
                }
                if !anytime.isEmpty {
                    section("today.anytime") {
                        VStack(spacing: Theme.Spacing.sm) {
                            ForEach(anytime) { item in anytimeRow(item) }
                        }
                    }
                }
                if !habits.today.isEmpty {
                    section("today.habits", trailing: habitCount) {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: Theme.Spacing.md) {
                                ForEach(habits.today) { h in
                                    HabitRing(title: h.text, checked: habits.checkedToday[h.id] != nil,
                                              streak: habits.streaks[h.id] ?? 0) {
                                        habits.toggle(api: state.api, h)
                                    }
                                    .contextMenu {
                                        Button { editingHabit = h } label: {
                                            Label(lang.s("blocks.edit"), systemImage: "pencil")
                                        }
                                        Button(role: .destructive) { habits.delete(api: state.api, h) } label: {
                                            Label(lang.s("blocks.delete"), systemImage: "trash")
                                        }
                                    }
                                    .accessibilityAction(named: lang.s("a11y.edit")) { editingHabit = h }
                                    .accessibilityAction(named: lang.s("a11y.delete")) {
                                        habits.delete(api: state.api, h)
                                    }
                                }
                            }
                            .animation(Animation.spring(response: 0.5, dampingFraction: 0.8).reduced,
                                       value: habits.today.map(\.id))
                        }
                    }
                }
                footer
            }
            .padding(.horizontal, Theme.Spacing.lg)
            .padding(.bottom, 120)
        }
        .scrollDismissesKeyboard(.interactively)
        .toolbar(.hidden, for: .navigationBar)
        .task { await reload() }
        .task { await nudge.loadIfNeeded(api: state.api) }
        .task { await weather.load(api: state.api) }
        .refreshable { await reload() }
        .onReceive(NotificationCenter.default.publisher(for: .sandyBlocksChanged)) { _ in
            Task { await reload() }
        }
        .sheet(isPresented: $showProfile) { NavigationStack { ProfileView() } }
        .sheet(item: $editingTask) { t in
            ItemEditSheet(title: lang.s("today.task"), item: t, isHabit: false,
                          save: { tasks.update(api: state.api, t, $0) },
                          delete: { tasks.delete(api: state.api, t) })
        }
        .sheet(item: $editingHabit) { h in
            ItemEditSheet(title: lang.s("today.habit"), item: h, isHabit: true,
                          save: { habits.update(api: state.api, h, $0) },
                          delete: { habits.delete(api: state.api, h) })
        }
        .sheet(item: $editingReminder) { r in
            ReminderEditSheet(title: lang.s("blocks.reminders"), item: r, allowRepeat: true,
                              save: { text, date, repeats in
                                  await reminders.update(api: state.api, r, text: text, at: date,
                                                         recurrence: repeats)
                              },
                              delete: { reminders.delete(api: state.api, r) })
        }
    }

    private var habitCount: String {
        let kept = habits.today.filter { habits.checkedToday[$0.id] != nil }.count
        return AppLocale.number(kept) + "/" + AppLocale.number(habits.today.count)
    }

    // MARK: - Data

    private func reload() async {
        async let a: Void = tasks.load(api: state.api)
        async let b: Void = habits.load(api: state.api)
        async let c: Void = reminders.load(api: state.api)
        async let d: Void = expenses.load(api: state.api)
        // The budget alert on a new expense needs this month's numbers.
        async let e: Void = LifeStatsStore.shared.load(api: state.api)
        _ = await (a, b, c, d, e)
    }

    private var spentToday: Double {
        expenses.entries.reduce(0) { sum, e in
            guard let at = NotificationManager.parseISO(e.at ?? ""), Calendar.current.isDateInToday(at) else {
                return sum
            }
            return sum + (e.amount ?? 0)
        }
    }

    /// Timed tasks up to the end of today (late ones included) and today's reminders.
    private var moments: [RibbonMoment] {
        let cal = Calendar.current
        let endOfDay = cal.startOfDay(for: Date()).addingTimeInterval(86_400)
        let taskMoments = tasks.items.compactMap { t -> RibbonMoment? in
            guard let d = NotificationManager.parseISO(t.due ?? ""), d < endOfDay else { return nil }
            return RibbonMoment(id: "t" + t.id, date: d, text: t.text, source: .task(t))
        }
        let reminderMoments = reminders.items.compactMap { r -> RibbonMoment? in
            guard let d = NotificationManager.parseISO(r.fireAt), d < endOfDay else { return nil }
            return RibbonMoment(id: "r" + r.id, date: d, text: r.text, source: .reminder(r))
        }
        return (taskMoments + reminderMoments).sorted { $0.date < $1.date }
    }

    /// Open tasks with no time today: they can happen whenever.
    private var anytime: [ListItem] {
        let timed = Set(moments.map(\.id))
        return tasks.items.filter { !timed.contains("t" + $0.id) && ($0.due ?? "").isEmpty }
    }

    /// The day in one sentence, from what is really there.
    private var briefing: String {
        let late = moments.filter { $0.date < Date() }.count
        let left = habits.today.filter { habits.checkedToday[$0.id] == nil }.count
        let open = tasks.items.count
        var parts: [String] = []
        if late > 0 { parts.append(String(format: lang.s("today.brief.late"), AppLocale.number(late))) }
        if open > 0 { parts.append(String(format: lang.s("today.brief.tasks"), AppLocale.number(open))) }
        if let next = moments.first(where: { $0.date >= Date() }) {
            let t = next.date.formatted(Date.FormatStyle(date: .omitted, time: .shortened)
                .locale(AppLocale.current))
            parts.append(String(format: lang.s("today.brief.next"), t))
        }
        if left > 0 { parts.append(String(format: lang.s("today.brief.habits"), AppLocale.number(left))) }
        guard !parts.isEmpty else {
            // Habits were there and all of them are kept: say so.
            return lang.s(habits.today.isEmpty ? "today.brief.free" : "today.brief.allDone")
        }
        return lang.s("today.brief.lead") + parts.joined(separator: lang.s("today.brief.join"))
    }

    // MARK: - Pieces

    /// Greeting and date on one side; the weather sits in the corner as plain information,
    /// like the clock on the lock screen, and the avatar opens your profile.
    /// Side by side; at the largest text sizes the greeting goes under the buttons.
    private var header: some View {
        let layout = typeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: Theme.Spacing.sm))
            : AnyLayout(HStackLayout(alignment: .top))
        return layout {
            VStack(alignment: .leading, spacing: 2) {
                Text(greeting)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
                Text(Date().formatted(Date.FormatStyle(date: .complete, time: .omitted)
                    .locale(AppLocale.current)))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.tertiaryText)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .accessibilityElement(children: .combine)
            if !typeSize.isAccessibilitySize { Spacer() }
            HStack(alignment: .top, spacing: Theme.Spacing.md) { buttons }
        }
        .padding(.top, Theme.Spacing.sm)
    }

    /// Focus, home, the weather in the corner, and the avatar that opens Profile.
    @ViewBuilder
    private var buttons: some View {
        HStack(spacing: Theme.Spacing.md) {
            // Focus drives the lock-screen Live Activity; home is the devices.
            NavigationLink { FocusView() } label: { Image(systemName: "target") }
                .accessibilityLabel(lang.s("today.focus"))
            NavigationLink { ControlView() } label: { Image(systemName: "house.fill") }
                .accessibilityLabel(lang.s("today.home"))
        }
        .scaledFont(17, weight: .semibold)
        .foregroundColor(Theme.Colors.accent)
        .padding(.top, 2)
        if let w = weather.snapshot {
            HStack(spacing: 4) {
                Image(systemName: w.symbol)
                Text("\(w.tempC)°")
            }
            .scaledFont(15, weight: .semibold, design: .rounded)
            .foregroundColor(Theme.Colors.secondaryText)
            .padding(.top, 2)
            .accessibilityElement(children: .combine)
        }
        Button { showProfile = true } label: { SandyAvatar(size: 34, mood: .happy) }
            .buttonStyle(.plain)
            .accessibilityLabel(lang.s("today.profile"))
    }

    private var greeting: String {
        let name = state.onboarding.preferredName.isEmpty ? state.onboarding.name
                                                           : state.onboarding.preferredName
        let h = Calendar.current.component(.hour, from: Date())
        let base = lang.s(h < 12 && h >= 5 ? "today.hello.morning"
                          : h < 18 && h >= 12 ? "today.hello.afternoon" : "today.hello.evening")
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        return trimmed.isEmpty ? base : base + " " + trimmed
    }

    private func section<C: View>(_ key: String, trailing: String? = nil,
                                  @ViewBuilder content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            HStack {
                Text(lang.s(key))
                Spacer()
                if let trailing { Text(trailing).contentTransition(.numericText()) }
            }
            .scaledFont(13, weight: .semibold, design: .rounded)
            .foregroundColor(Theme.Colors.tertiaryText)
            .textCase(.uppercase)
            .accessibilityAddTraits(.isHeader)
            content()
        }
    }

    private func anytimeRow(_ item: ListItem) -> some View {
        HStack(spacing: Theme.Spacing.md) {
            Button { withAnimation { tasks.toggle(api: state.api, item) } } label: {
                Image(systemName: "circle")
                    .scaledFont(Theme.Icon.md)
                    .foregroundColor(Theme.Colors.accent)
            }
            .buttonStyle(.plain)
            Text(item.text)
                .font(Theme.Typography.body)
                .foregroundColor(Theme.Colors.primaryText)
            Spacer(minLength: 0)
            if item.priority == "high" {
                Image(systemName: "flag.fill").foregroundColor(Theme.Colors.warn)
            }
        }
        .padding(.vertical, 10)
        .padding(.horizontal, Theme.Spacing.md)
        .background(RoundedRectangle(cornerRadius: 14).fill(Theme.Colors.surface.opacity(0.45)))
        .contentShape(RoundedRectangle(cornerRadius: 14))
        .onTapGesture { editingTask = item }
        .contextMenu {
            Button { editingTask = item } label: { Label(lang.s("blocks.edit"), systemImage: "pencil") }
            Button(role: .destructive) { tasks.delete(api: state.api, item) } label: {
                Label(lang.s("blocks.delete"), systemImage: "trash")
            }
        }
        .rowAccessibility(label: A11yText.item(item, habits: false, streak: nil),
                          value: lang.s("a11y.notDone"), hint: lang.s("a11y.rowHint"),
                          open: { editingTask = item },
                          actions: [(lang.s("a11y.markDone"), { tasks.toggle(api: state.api, item) }),
                                    (lang.s("a11y.delete"), { tasks.delete(api: state.api, item) })])
    }

    /// Today's spending, quietly at the bottom.
    @ViewBuilder
    private var footer: some View {
        if spentToday > 0 {
            NavigationLink { LogView(kind: "expense") } label: {
                HStack {
                    Label(String(format: lang.s("today.spent"), AppLocale.number(spentToday)),
                          systemImage: "creditcard")
                    Image(systemName: "chevron.forward").font(.caption)
                }
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
            }
            .buttonStyle(.plain)
            .padding(.top, Theme.Spacing.sm)
        }
    }
}
