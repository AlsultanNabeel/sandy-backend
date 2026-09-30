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
    @State private var spentToday: Double = 0
    @State private var showProfile = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                header
                Text(briefing)
                    .font(.system(size: 26, weight: .bold, design: .rounded))
                    .foregroundColor(Theme.Colors.primaryText)
                    .fixedSize(horizontal: false, vertical: true)
                    .contentTransition(.opacity)
                AskBar { await reload() }
                if nudge.nudge != nil && !nudge.dismissed { DailyNudgeCard(store: nudge) }
                section("today.restOfDay") {
                    DayRibbon(moments: moments) { tasks.toggle(api: state.api, $0) }
                }
                if !anytime.isEmpty {
                    section("today.anytime") {
                        VStack(spacing: Theme.Spacing.sm) {
                            ForEach(anytime) { item in anytimeRow(item) }
                        }
                    }
                }
                if !habits.items.isEmpty {
                    section("today.habits") {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: Theme.Spacing.md) {
                                ForEach(habits.items) { h in
                                    HabitRing(title: h.text, checked: habits.checkedToday[h.id] != nil) {
                                        habits.toggle(api: state.api, h)
                                    }
                                }
                            }
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
        .sheet(isPresented: $showProfile) { NavigationStack { ProfileView() } }
    }

    // MARK: - Data

    private func reload() async {
        async let a: Void = tasks.load(api: state.api)
        async let b: Void = habits.load(api: state.api)
        async let c: Void = reminders.load(api: state.api)
        async let d = (try? await state.api.entries(kind: "expense", limit: 50)) ?? []
        let (_, _, _, spent) = await (a, b, c, d)
        let cal = Calendar.current
        spentToday = spent.reduce(0) { sum, e in
            guard let at = NotificationManager.parseISO(e.at ?? ""), cal.isDateInToday(at) else { return sum }
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
        let left = habits.items.filter { habits.checkedToday[$0.id] == nil }.count
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
        guard !parts.isEmpty else { return lang.s("today.brief.free") }
        return lang.s("today.brief.lead") + parts.joined(separator: lang.s("today.brief.join"))
    }

    // MARK: - Pieces

    /// Greeting and date on one side; the weather sits in the corner as plain information,
    /// like the clock on the lock screen, and the avatar opens your profile.
    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 2) {
                Text(greeting)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.secondaryText)
                Text(Date().formatted(Date.FormatStyle(date: .complete, time: .omitted)
                    .locale(AppLocale.current)))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.tertiaryText)
            }
            Spacer()
            if let w = weather.snapshot {
                HStack(spacing: 4) {
                    Image(systemName: w.symbol)
                    Text("\(w.tempC)°")
                }
                .font(.system(size: 15, weight: .semibold, design: .rounded))
                .foregroundColor(Theme.Colors.secondaryText)
                .padding(.top, 2)
                .accessibilityElement(children: .combine)
            }
            Button { showProfile = true } label: { SandyAvatar(size: 34, mood: .happy) }
                .buttonStyle(.plain)
                .accessibilityLabel(lang.s("today.profile"))
        }
        .padding(.top, Theme.Spacing.sm)
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

    private func section<C: View>(_ key: String, @ViewBuilder content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Text(lang.s(key))
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundColor(Theme.Colors.tertiaryText)
                .textCase(.uppercase)
            content()
        }
    }

    private func anytimeRow(_ item: ListItem) -> some View {
        HStack(spacing: Theme.Spacing.md) {
            Button { tasks.toggle(api: state.api, item) } label: {
                Image(systemName: "circle")
                    .font(.system(size: Theme.Icon.md))
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
    }

    /// Today's spending, focus and the home's devices, quietly at the bottom.
    private var footer: some View {
        HStack(spacing: Theme.Spacing.md) {
            if spentToday > 0 {
                Label(String(format: lang.s("today.spent"), AppLocale.number(spentToday)),
                      systemImage: "creditcard")
            }
            Spacer()
            // Focus stays one tap away: it drives the lock-screen Live Activity.
            NavigationLink { FocusView() } label: {
                Label(lang.s("today.focus"), systemImage: "target")
            }
            NavigationLink { ControlView() } label: {
                Label(lang.s("today.home"), systemImage: "house.fill")
            }
        }
        .font(Theme.Typography.subheadline)
        .foregroundColor(Theme.Colors.secondaryText)
        .padding(.top, Theme.Spacing.sm)
    }
}
