import SwiftUI

/// تبويب الخط الزمني — سجل نشاطك الموحّد (مهام/تذكيرات/مصاريف/يوميات) مرتّب
/// بالوقت ومجمّع (اليوم/أمس/الأسبوع/أقدم). حرية كاملة: احذف أي عنصر بالسحب
/// (يُحذف من مصدره فعليًا). الإضافة والتعديل التفصيلي بتبويب كل ميزة.
/// (الاسم `TimelineTabView` تجنّبًا لتعارض `TimelineView` المدمج بـ SwiftUI.)
struct TimelineTabView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = TimelineStore()
    /// الحدث المفتوح بلوحة التفاصيل (nil = مغلقة).
    @State private var detail: TimelineEvent?

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
        .fullScreenCover(item: $detail) { ev in
            TimelineDetailSheet(
                event: ev,
                typeLabel: typeLabel(ev.type),
                icon: icon(ev),
                tint: tint(ev),
                onToggleDone: { store.toggleTask(api: state.api, event: ev); detail = nil },
                onDelete: { store.delete(api: state.api, event: ev); detail = nil }
            )
        }
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
                                .contentShape(Rectangle())
                                .onTapGesture { detail = ev }
                                .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                    Button(role: .destructive) {
                                        store.delete(api: state.api, event: ev)
                                    } label: { Label(lang.s("timeline.delete"), systemImage: "trash") }
                                }
                                .swipeActions(edge: .leading) {
                                    // أداة سريعة حسب النوع: المهمة تنعلّم منجزة بالسحب لليمين.
                                    if ev.type == "task" {
                                        Button {
                                            store.toggleTask(api: state.api, event: ev)
                                        } label: {
                                            Label(lang.s(ev.done ? "timeline.markUndone" : "timeline.markDone"),
                                                  systemImage: ev.done ? "arrow.uturn.left" : "checkmark.circle")
                                        }
                                        .tint(Theme.Colors.success)
                                    }
                                }
                                .contextMenu {
                                    Button { detail = ev } label: {
                                        Label(lang.s("timeline.detailsAction"), systemImage: "info.circle")
                                    }
                                    if ev.type == "task" {
                                        Button {
                                            store.toggleTask(api: state.api, event: ev)
                                        } label: {
                                            Label(lang.s(ev.done ? "timeline.markUndone" : "timeline.markDone"),
                                                  systemImage: ev.done ? "arrow.uturn.left" : "checkmark.circle")
                                        }
                                    }
                                    Button(role: .destructive) {
                                        store.delete(api: state.api, event: ev)
                                    } label: { Label(lang.s("timeline.delete"), systemImage: "trash") }
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
                .font(.system(size: Theme.Icon.md, weight: .semibold))
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
                .font(.system(size: Theme.Icon.xl))
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

// MARK: - لوحة تفاصيل الحدث

/// لوحة تفاصيل حدث الخط الزمني: العنوان الكامل + النوع + الوقت، مع أدوات سريعة
/// حسب النوع (المهمة: تعليم منجز) وحذف. التعديل التفصيلي يبقى بتبويب كل ميزة —
/// فالخط الزمني تجميعي، ونتجنّب تكرار أربع محرّرات (أقل احتمالية للأخطاء).
private struct TimelineDetailSheet: View {
    let event: TimelineEvent
    let typeLabel: String
    let icon: String
    let tint: Color
    let onToggleDone: () -> Void
    let onDelete: () -> Void

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        SandyPopup(title: lang.s("timeline.detailTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                // ترويسة: أيقونة النوع + شارة النوع.
                HStack(spacing: Theme.Spacing.md) {
                    Image(systemName: icon)
                        .font(.system(size: Theme.Icon.lg, weight: .semibold))
                        .foregroundColor(tint)
                    Text(typeLabel)
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .padding(.vertical, Theme.Spacing.xs)
                        .padding(.horizontal, Theme.Spacing.sm)
                        .background(tint.opacity(0.12))
                        .clipShape(Capsule())
                    Spacer(minLength: 0)
                }

                SandyCard {
                    VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                        Text(event.title.isEmpty ? typeLabel : event.title)
                            .font(Theme.Typography.headline)
                            .foregroundColor(Theme.Colors.primaryText)
                            .strikethrough(event.done, color: Theme.Colors.secondaryText)
                            .fixedSize(horizontal: false, vertical: true)
                        if !event.subtitle.isEmpty {
                            Text(event.subtitle)
                                .font(Theme.Typography.body)
                                .foregroundColor(Theme.Colors.secondaryText)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        if let when = Self.format(event.ts) {
                            Label(when, systemImage: "clock")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.secondaryText)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                // أداة سريعة حسب النوع: المهمة تنعلّم منجزة/غير منجزة.
                if event.type == "task" {
                    SandyButton(title: lang.s(event.done ? "timeline.markUndone" : "timeline.markDone"),
                                systemImage: event.done ? "arrow.uturn.left" : "checkmark.circle.fill",
                                fillWidth: true) {
                        onToggleDone()
                    }
                }

                SandyButton(title: lang.s("timeline.delete"),
                            systemImage: "trash",
                            style: .secondary,
                            fillWidth: true) {
                    onDelete()
                }

                Text(lang.s("timeline.detailHint"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    /// تنسيق وقت ISO لعرض عربي لطيف.
    private static func format(_ iso: String) -> String? {
        guard !iso.isEmpty else { return nil }
        let full = ISO8601DateFormatter()
        full.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        let date = full.date(from: iso) ?? plain.date(from: iso)
        guard let d = date else { return nil }
        let out = DateFormatter()
        out.locale = Locale(identifier: "ar")
        out.dateStyle = .medium
        out.timeStyle = .short
        return out.string(from: d)
    }
}

// MARK: - الستور
