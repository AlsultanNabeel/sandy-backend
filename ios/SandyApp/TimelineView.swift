import SwiftUI

/// تبويب الخط الزمني — سجل نشاطك الموحّد (مهام/تذكيرات/مصاريف/يوميات) مرتّب
/// بالوقت ومجمّع (اليوم/أمس/الأسبوع/أقدم). حرية كاملة: احذف أي عنصر بالسحب
/// (يُحذف من مصدره فعليًا). الإضافة والتعديل التفصيلي بتبويب كل ميزة.
/// (الاسم `TimelineTabView` تجنّبًا لتعارض `TimelineView` المدمج بـ SwiftUI.)
struct TimelineTabView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = TimelineStore()

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                content
            }
        }
        .navigationTitle(lang.s("tabs.timeline"))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
    }

    @ViewBuilder
    private var content: some View {
        if store.events.isEmpty && !store.loading {
            emptyView
        } else {
            List {
                ForEach(store.grouped, id: \.0) { bucket, events in
                    Section(lang.s("timeline.\(bucket)")) {
                        ForEach(events) { ev in
                            row(ev)
                                .listRowBackground(Color.clear)
                                .swipeActions {
                                    Button(role: .destructive) {
                                        store.delete(api: state.api, event: ev)
                                    } label: { Image(systemName: "trash") }
                                }
                        }
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
    }

    private func row(_ ev: TimelineEvent) -> some View {
        HStack(spacing: Theme.Spacing.md) {
            Image(systemName: icon(ev))
                .font(.callout)
                .foregroundColor(tint(ev))
                .frame(width: 26)
            VStack(alignment: .leading, spacing: 2) {
                Text(ev.title.isEmpty ? typeLabel(ev.type) : ev.title)
                    .font(Theme.Typography.body)
                    .foregroundColor(Theme.Colors.primaryText)
                    .strikethrough(ev.done, color: Theme.Colors.secondaryText)
                    .lineLimit(1)
                if !ev.subtitle.isEmpty {
                    Text(ev.subtitle)
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
            Text(typeLabel(ev.type))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
        }
        .padding(.vertical, 2)
        .contentShape(Rectangle())
    }

    private var emptyView: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "clock.badge.checkmark")
                .font(.system(size: 44))
                .foregroundColor(Theme.Colors.accent.opacity(0.5))
            Text(lang.s("timeline.empty"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Theme.Spacing.lg)
    }

    private func icon(_ ev: TimelineEvent) -> String {
        switch ev.type {
        case "task":     return ev.done ? "checkmark.circle.fill" : "circle"
        case "reminder": return "bell.fill"
        case "expense":  return "creditcard.fill"
        case "journal":  return "book.fill"
        default:         return "circle.fill"
        }
    }

    private func tint(_ ev: TimelineEvent) -> Color {
        switch ev.type {
        case "task":     return ev.done ? Theme.Colors.success : Theme.Colors.accent
        case "reminder": return Theme.Colors.warn
        case "expense":  return Theme.Colors.danger
        case "journal":  return Theme.Colors.accent
        default:         return Theme.Colors.secondaryText
        }
    }

    private func typeLabel(_ type: String) -> String { lang.s("timeline.type.\(type)") }
}

// MARK: - الستور

@MainActor
final class TimelineStore: ObservableObject {
    @Published var events: [TimelineEvent] = []
    @Published var loading = false
    @Published var notice = ""

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                events = try await api.getTimeline()
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("timeline.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// حذف متفائل فوري من الخط، ثم حذف المصدر حسب النوع؛ يرجع العنصر عند الفشل.
    func delete(api: APIClient, event: TimelineEvent) {
        guard let idx = events.firstIndex(where: { $0.id == event.id }) else { return }
        events.remove(at: idx)
        Task { @MainActor in
            do {
                switch event.type {
                case "task":     try await api.deleteTask(id: event.id)
                case "reminder": try await api.deleteReminder(id: event.id)
                case "expense":  try await api.deleteExpense(id: event.id)
                case "journal":  try await api.deleteJournalEntry(id: event.id)
                default: break
                }
            } catch {
                events.insert(event, at: min(idx, events.count))
                notice = LanguageManager.shared.s("timeline.errorDelete")
            }
        }
    }

    /// الأحداث مجمّعة زمنيًا (اليوم/أمس/الأسبوع/أقدم)، فاضي تُحذف، والترتيب محفوظ.
    var grouped: [(String, [TimelineEvent])] {
        let order = ["today", "yesterday", "week", "older"]
        var map: [String: [TimelineEvent]] = [:]
        for e in events { map[bucket(e.ts), default: []].append(e) }
        return order.compactMap { key in
            guard let evs = map[key], !evs.isEmpty else { return nil }
            return (key, evs)
        }
    }

    private func bucket(_ iso: String) -> String {
        guard let d = parseISO(iso) else { return "older" }
        let cal = Calendar.current
        if cal.isDateInToday(d) { return "today" }
        if cal.isDateInYesterday(d) { return "yesterday" }
        if let days = cal.dateComponents([.day], from: d, to: Date()).day, days < 7 { return "week" }
        return "older"
    }

    private func parseISO(_ iso: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: iso) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: iso)
    }
}
