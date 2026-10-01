import SwiftUI

/// One moment on the day ribbon: a timed task or a reminder.
struct RibbonMoment: Identifiable {
    enum Source { case task(ListItem), reminder(ScheduleItem) }
    let id: String
    let date: Date
    let text: String
    let source: Source
}

/// The rest of today as a vertical line: what is late sits above in amber, a light marks
/// "now" and moves with the clock, and each thing waits at its own time below it.
struct DayRibbon: View {
    @EnvironmentObject var lang: LanguageManager
    let moments: [RibbonMoment]
    /// Ticked: a task is done, a one-off reminder is closed.
    let onDone: (RibbonMoment.Source) -> Void
    /// Tapped: opens its edit sheet.
    let onOpen: (RibbonMoment.Source) -> Void
    let onSnooze: (ScheduleItem, Int) -> Void
    let onDelete: (RibbonMoment.Source) -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { context in
            let now = context.date
            let late = moments.filter { $0.date < now }
            let ahead = moments.filter { $0.date >= now }
            VStack(alignment: .leading, spacing: 0) {
                ForEach(late) { row($0, late: true) }
                nowMark(now)
                ForEach(ahead) { row($0, late: false) }
                if ahead.isEmpty {
                    Text(lang.s("today.restFree"))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.tertiaryText)
                        .padding(.leading, 64)
                        .padding(.vertical, Theme.Spacing.sm)
                }
            }
        }
    }

    private func time(_ date: Date) -> String {
        date.formatted(Date.FormatStyle(date: .omitted, time: .shortened).locale(AppLocale.current))
    }

    private func row(_ m: RibbonMoment, late: Bool) -> some View {
        HStack(alignment: .center, spacing: Theme.Spacing.sm) {
            Text(time(m.date))
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .foregroundColor(late ? Theme.Colors.warn : Theme.Colors.secondaryText)
                .frame(width: 52, alignment: .trailing)
            ZStack {
                Rectangle().fill(Theme.Colors.border).frame(width: 2)
                Circle()
                    .fill(late ? Theme.Colors.warn : Theme.Colors.surface)
                    .overlay(Circle().stroke(late ? Theme.Colors.warn : Theme.Colors.accent, lineWidth: 2))
                    .frame(width: 12, height: 12)
            }
            .frame(width: 14)
            HStack(spacing: Theme.Spacing.sm) {
                switch m.source {
                case .task:
                    Button { onDone(m.source) } label: {
                        Image(systemName: "circle").foregroundColor(Theme.Colors.accent)
                    }
                    .buttonStyle(.plain)
                case .reminder(let r):
                    if (r.recurrence ?? "").isEmpty {
                        Button { onDone(m.source) } label: {
                            Image(systemName: "bell.circle").foregroundColor(Theme.Colors.warn)
                        }
                        .buttonStyle(.plain)
                    } else {
                        Image(systemName: "repeat.circle").foregroundColor(Theme.Colors.warn)
                    }
                }
                Text(m.text)
                    .font(Theme.Typography.body)
                    .foregroundColor(Theme.Colors.primaryText)
                    .lineLimit(2)
                Spacer(minLength: 0)
                if case .task(let item) = m.source, item.priority == "high" {
                    Image(systemName: "flag.fill").foregroundColor(Theme.Colors.warn)
                }
            }
            .padding(.vertical, 10)
            .padding(.horizontal, Theme.Spacing.md)
            .background(RoundedRectangle(cornerRadius: 14)
                .fill(late ? Theme.Colors.warnSoft.opacity(0.7) : Theme.Colors.surface.opacity(0.45)))
            .contentShape(RoundedRectangle(cornerRadius: 14))
            .onTapGesture { onOpen(m.source) }
            .contextMenu { menu(m) }
            .padding(.vertical, 3)
        }
    }

    /// A repeating reminder has no "done": it comes back on its own.
    private static func canClose(_ source: RibbonMoment.Source) -> Bool {
        if case .reminder(let r) = source { return (r.recurrence ?? "").isEmpty }
        return true
    }

    @ViewBuilder
    private func menu(_ m: RibbonMoment) -> some View {
        if case .reminder(let r) = m.source {
            Button { onSnooze(r, 15) } label: {
                Label(lang.s("blocks.quick.15"), systemImage: "clock.arrow.circlepath")
            }
            Button { onSnooze(r, 60) } label: {
                Label(lang.s("blocks.quick.hour"), systemImage: "clock.arrow.circlepath")
            }
        }
        if Self.canClose(m.source) {
            Button { onDone(m.source) } label: { Label(lang.s("blocks.markDone"), systemImage: "checkmark") }
        }
        Button { onOpen(m.source) } label: { Label(lang.s("blocks.edit"), systemImage: "pencil") }
        Button(role: .destructive) { onDelete(m.source) } label: {
            Label(lang.s("blocks.delete"), systemImage: "trash")
        }
    }

    private func nowMark(_ now: Date) -> some View {
        HStack(spacing: Theme.Spacing.sm) {
            Text(lang.s("today.now"))
                .font(.system(size: 12, weight: .bold, design: .rounded))
                .foregroundColor(Theme.Colors.accent)
                .frame(width: 52, alignment: .trailing)
            NowPulse().frame(width: 14)
            Rectangle()
                .fill(LinearGradient(colors: [Theme.Colors.accent, .clear],
                                     startPoint: .leading, endPoint: .trailing))
                .frame(height: 2)
        }
        .padding(.vertical, 6)
    }
}

/// The "now" dot: a soft light breathing on the line.
private struct NowPulse: View {
    @State private var on = false
    var body: some View {
        ZStack {
            Circle().fill(Theme.Colors.accent.opacity(0.25))
                .frame(width: on ? 22 : 12, height: on ? 22 : 12)
            Circle().fill(Theme.Colors.accent).frame(width: 10, height: 10)
                .shadow(color: Theme.Colors.accent, radius: 6)
        }
        .frame(height: 22)
        .onAppear {
            withAnimation(.easeInOut(duration: 1.4).repeatForever(autoreverses: true)) { on = true }
        }
    }
}

/// A habit as a ring that fills when you tap it today.
struct HabitRing: View {
    let title: String
    let checked: Bool
    var streak = 0
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 6) {
                ZStack {
                    Circle().stroke(Theme.Colors.surface, lineWidth: 5)
                    Circle()
                        .trim(from: 0, to: checked ? 1 : 0)
                        .stroke(AngularGradient(colors: [Theme.Colors.success, Theme.Colors.accent,
                                                         Theme.Colors.success], center: .center),
                                style: StrokeStyle(lineWidth: 5, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                    Image(systemName: checked ? "checkmark" : "plus")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundColor(checked ? Theme.Colors.success : Theme.Colors.secondaryText)
                }
                .frame(width: 54, height: 54)
                .animation(.spring(response: 0.6, dampingFraction: 0.7), value: checked)
                Text(title)
                    .font(Theme.Typography.caption)
                    .foregroundColor(checked ? Theme.Colors.secondaryText : Theme.Colors.primaryText)
                    .lineLimit(1)
                    .frame(width: 70)
                // Same height either way, so rings stay in line.
                StreakBadge(days: streak).opacity(streak > 1 ? 1 : 0)
            }
        }
        .buttonStyle(.plain)
        .sensoryFeedback(.success, trigger: checked) { _, now in now }
    }
}
