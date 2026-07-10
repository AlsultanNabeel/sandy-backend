import SwiftUI

/// تبويب المشاريع — عصف ذهني كامل الدورة: ابدأ جلسة، ضيف أفكار، خلّص لخطة أو
/// ألغِ، وعدّل/احذف أي خطة محفوظة. نمط الستور المعتمد: الجلب بمهمة يملكها الستور.
struct ProjectsView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = ProjectsStore()
    @State private var showStart = false
    @State private var detail: ProjectPlan?
    @State private var newPoint = ""
    @State private var confirmCancel = false

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
        .navigationTitle(lang.s("tabs.projects"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                if store.active == nil {
                    SandyButton(title: lang.s("projects.start"),
                                systemImage: "plus.circle.fill",
                                style: .secondary) {
                        store.notice = ""
                        showStart = true
                    }
                }
            }
        }
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .fullScreenCover(isPresented: $showStart) {
            StartBrainstormSheet { topic in await store.start(api: state.api, topic: topic) }
        }
        .fullScreenCover(item: $detail) { plan in
            ProjectDetailSheet(
                plan: plan,
                onUpdate: { change in await store.update(api: state.api, id: plan.id, change: change) },
                onDelete: { store.delete(api: state.api, plan: plan); detail = nil }
            )
        }
        .alert(lang.s("projects.cancel"), isPresented: $confirmCancel) {
            Button(lang.s("projects.cancel"), role: .destructive) {
                store.cancel(api: state.api)
            }
            Button(lang.s("common.cancel"), role: .cancel) {}
        } message: {
            Text(lang.s("projects.cancelConfirm"))
        }
    }

    @ViewBuilder
    private var content: some View {
        if store.plans.isEmpty && store.active == nil && !store.loading {
            emptyView
        } else {
            List {
                if let active = store.active {
                    activeSection(active)
                }
                if !store.plans.isEmpty {
                    header
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: Theme.Spacing.sm, leading: Theme.Spacing.md,
                                                  bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                    ForEach(store.plans) { plan in
                        planCard(plan)
                            .listRowBackground(Color.clear)
                            .listRowSeparator(.hidden)
                            .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                      bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                            .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                Button(role: .destructive) {
                                    store.delete(api: state.api, plan: plan)
                                } label: { Label(lang.s("projects.delete"), systemImage: "trash") }
                            }
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
    }

    // MARK: - الجلسة النشطة

    @ViewBuilder
    private func activeSection(_ active: ActiveBrainstorm) -> some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                HStack(spacing: Theme.Spacing.sm) {
                    Image(systemName: "bolt.fill")
                        .foregroundColor(Theme.Colors.accent)
                    Text(active.topic.isEmpty ? lang.s("projects.activeTitle") : active.topic)
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Spacer(minLength: 0)
                }

                if active.points.isEmpty {
                    Text(lang.s("projects.pointsEmpty"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                } else {
                    VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                        ForEach(Array(active.points.enumerated()), id: \.offset) { _, p in
                            HStack(alignment: .top, spacing: Theme.Spacing.sm) {
                                Image(systemName: "circle.fill")
                                    .font(.system(size: 5))
                                    .foregroundColor(Theme.Colors.secondaryText)
                                    .padding(.top, 6)
                                Text(p)
                                    .font(Theme.Typography.body)
                                    .foregroundColor(Theme.Colors.primaryText)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }

                HStack(spacing: Theme.Spacing.sm) {
                    TextField(lang.s("projects.addPointPlaceholder"), text: $newPoint, axis: .vertical)
                        .font(Theme.Typography.body)
                        .lineLimit(1...4)
                    Button {
                        let text = newPoint.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !text.isEmpty else { return }
                        newPoint = ""
                        store.addPoint(api: state.api, point: text)
                    } label: {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: Theme.Icon.md))
                            .foregroundColor(Theme.Colors.accent)
                    }
                    .disabled(newPoint.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }

                HStack(spacing: Theme.Spacing.sm) {
                    SandyButton(title: lang.s("projects.finish"),
                                systemImage: "checkmark.circle.fill",
                                isLoading: store.finishing,
                                fillWidth: true) {
                        store.finish(api: state.api)
                    }
                    Button {
                        confirmCancel = true
                    } label: {
                        Image(systemName: "xmark.circle")
                            .font(.system(size: Theme.Icon.md))
                            .foregroundColor(Theme.Colors.danger)
                    }
                }
            }
        }
        .listRowBackground(Color.clear)
        .listRowSeparator(.hidden)
        .listRowInsets(EdgeInsets(top: Theme.Spacing.sm, leading: Theme.Spacing.md,
                                  bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
    }

    private var header: some View {
        Text(lang.s("projects.intro"))
            .font(Theme.Typography.subheadline)
            .foregroundColor(Theme.Colors.secondaryText)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func planCard(_ plan: ProjectPlan) -> some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                HStack(alignment: .top, spacing: Theme.Spacing.md) {
                    Image(systemName: "lightbulb.fill")
                        .font(.system(size: Theme.Icon.sm, weight: .semibold))
                        .foregroundColor(Theme.Colors.accent)
                        .padding(.top, 3)
                    Text(plan.topic.isEmpty ? lang.s("projects.untitled") : plan.topic)
                        .font(Theme.Typography.body)
                        .foregroundColor(Theme.Colors.primaryText)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if !plan.summary.isEmpty {
                    Text(plan.summary)
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .lineLimit(2)
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { detail = plan }
        .contextMenu {
            Button { detail = plan } label: {
                Label(lang.s("projects.edit"), systemImage: "pencil")
            }
            Button(role: .destructive) {
                store.delete(api: state.api, plan: plan)
            } label: { Label(lang.s("projects.delete"), systemImage: "trash") }
        }
    }

    private var emptyView: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "lightbulb.max.fill")
                .font(.system(size: Theme.Icon.xl))
                .foregroundColor(Theme.Colors.accent.opacity(0.5))
            Text(lang.s("projects.empty"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
            SandyButton(title: lang.s("projects.start"),
                        systemImage: "plus.circle.fill") {
                store.notice = ""
                showStart = true
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Theme.Spacing.lg)
    }
}

// MARK: - ورقة بدء جلسة جديدة

private struct StartBrainstormSheet: View {
    let onStart: (_ topic: String) async -> Bool

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var topic = ""
    @State private var submitting = false

    private var trimmed: String { topic.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        SandyPopup(title: lang.s("projects.startTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                SandyCard {
                    TextField(lang.s("projects.startPlaceholder"), text: $topic, axis: .vertical)
                        .font(Theme.Typography.body)
                        .lineLimit(2...5)
                }
                SandyButton(title: lang.s("projects.startAction"),
                            systemImage: "bolt.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    guard !trimmed.isEmpty, !submitting else { return }
                    submitting = true
                    Task {
                        let ok = await onStart(trimmed)
                        submitting = false
                        if ok { dismiss() }
                    }
                }
                .disabled(trimmed.isEmpty)
                .opacity(trimmed.isEmpty ? 0.5 : 1)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }
}

// MARK: - لوحة تفاصيل الخطة

private struct ProjectDetailSheet: View {
    let plan: ProjectPlan
    let onUpdate: (_ change: String) async -> Bool
    let onDelete: () -> Void

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var showEdit = false
    @State private var confirmDelete = false

    var body: some View {
        SandyPopup(title: lang.s("projects.detailTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                SandyCard {
                    VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                        Text(plan.topic.isEmpty ? lang.s("projects.untitled") : plan.topic)
                            .font(Theme.Typography.headline)
                            .foregroundColor(Theme.Colors.primaryText)
                            .fixedSize(horizontal: false, vertical: true)
                        if let dateText = Self.format(plan.finishedAt) {
                            Label(dateText, systemImage: "clock")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.secondaryText)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                if !plan.planText.isEmpty {
                    SandyCard {
                        Text(plan.planText)
                            .font(Theme.Typography.body)
                            .foregroundColor(Theme.Colors.primaryText)
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                HStack(spacing: Theme.Spacing.sm) {
                    SandyButton(title: lang.s("projects.edit"),
                                systemImage: "pencil",
                                fillWidth: true) {
                        showEdit = true
                    }
                    SandyButton(title: lang.s("projects.delete"),
                                systemImage: "trash",
                                style: .secondary,
                                fillWidth: true) {
                        confirmDelete = true
                    }
                }

                Text(lang.s("projects.detailHint"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
        .fullScreenCover(isPresented: $showEdit) {
            EditPlanSheet { change in
                let ok = await onUpdate(change)
                if ok { dismiss() }
                return ok
            }
        }
        .alert(lang.s("projects.delete"), isPresented: $confirmDelete) {
            Button(lang.s("projects.delete"), role: .destructive) { onDelete() }
            Button(lang.s("common.cancel"), role: .cancel) {}
        } message: {
            Text(lang.s("projects.deleteConfirm"))
        }
    }

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

// MARK: - ورقة تعديل الخطة

private struct EditPlanSheet: View {
    /// يرجع true لو نجح التحديث — الأب بيسكّر لوحة التفاصيل بعدها.
    let onSubmit: (_ change: String) async -> Bool

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var change = ""
    @State private var submitting = false

    private var trimmed: String { change.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        SandyPopup(title: lang.s("projects.editTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                SandyCard {
                    TextField(lang.s("projects.editPlaceholder"), text: $change, axis: .vertical)
                        .font(Theme.Typography.body)
                        .lineLimit(2...6)
                }
                SandyButton(title: lang.s("projects.editAction"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    guard !trimmed.isEmpty, !submitting else { return }
                    submitting = true
                    Task {
                        let ok = await onSubmit(trimmed)
                        submitting = false
                        if ok { dismiss() }
                    }
                }
                .disabled(trimmed.isEmpty)
                .opacity(trimmed.isEmpty ? 0.5 : 1)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }
}

// MARK: - الستور
