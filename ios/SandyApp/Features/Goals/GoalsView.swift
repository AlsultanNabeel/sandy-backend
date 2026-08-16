import SwiftUI

/// شاشة الأهداف — تعرض الأهداف اللي ساندي قاعدة تتابعك عليها (`sandy_goals`) عبر
/// `/api/goals`. CRUD كامل: إضافة، تعديل (نص + موعد)، تعليم كمكتمل/إرجاعه نشط،
/// وحذف. مقسومة لقسمين نشطة/مكتملة عشان تبيّن حالة كل هدف. نمط الستور المعتمد:
/// الجلب بمهمة يملكها الستور (مرآة MemoryView).
struct GoalsView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = GoalsStore()
    @State private var showAdd = false
    /// الهدف الجاري تعديله (nil = ما في ورقة تعديل مفتوحة).
    @State private var editingGoal: GoalItem?

    var body: some View {
        // الخلفية موحّدة على مستوى MainTabView — لا نكرّرها هون (طبقة مهدورة).
        ZStack {
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
        .navigationTitle(lang.s("goals.title"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                SandyButton(title: lang.s("goals.add"),
                            systemImage: "plus.circle.fill",
                            style: .secondary) {
                    store.notice = ""
                    showAdd = true
                }
            }
        }
        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.goals.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .fullScreenCover(isPresented: $showAdd) {
            GoalSheet { text, deadline in
                await store.add(api: state.api, text: text, deadline: deadline)
            }
        }
        .fullScreenCover(item: $editingGoal) { goal in
            GoalSheet(existing: goal) { text, deadline in
                await store.update(api: state.api, id: goal.id, text: text, deadline: deadline)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if store.goals.isEmpty && !store.loading {
            emptyView
        } else {
            List {
                // المقدّمة صف غير قابل للسحب يبقى أعلى القائمة.
                header
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: Theme.Spacing.sm, leading: Theme.Spacing.md,
                                              bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                section(title: lang.s("goals.section.active"), goals: store.active)
                section(title: lang.s("goals.section.done"), goals: store.done)
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
    }

    @ViewBuilder
    private func section(title: String, goals: [GoalItem]) -> some View {
        if !goals.isEmpty {
            SectionHeader(title: title)
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
                .listRowInsets(EdgeInsets(top: Theme.Spacing.md, leading: Theme.Spacing.md,
                                          bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
            ForEach(goals) { goal in
                goalCard(goal)
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                              bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                    .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                        Button(role: .destructive) {
                            store.delete(api: state.api, goal: goal)
                        } label: { Label(lang.s("goals.delete"), systemImage: "trash") }
                    }
                    .swipeActions(edge: .leading) {
                        Button { store.toggleDone(api: state.api, goal: goal) } label: {
                            Label(lang.s(goal.isDone ? "goals.reopen" : "goals.markDone"),
                                  systemImage: goal.isDone ? "arrow.uturn.backward" : "checkmark")
                        }
                        .tint(goal.isDone ? Theme.Colors.accent : Theme.Colors.success)
                    }
            }
        }
    }

    private var header: some View {
        Text(lang.s("goals.intro"))
            .font(Theme.Typography.subheadline)
            .foregroundColor(Theme.Colors.secondaryText)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func goalCard(_ goal: GoalItem) -> some View {
        SandyCard {
            HStack(alignment: .top, spacing: Theme.Spacing.md) {
                Image(systemName: goal.isDone ? "checkmark.circle.fill" : "target")
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(goal.isDone ? Theme.Colors.success : Theme.Colors.accent)
                    .padding(.top, Theme.Spacing.xs)
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(goal.text)
                        .font(Theme.Typography.body)
                        .foregroundColor(Theme.Colors.primaryText)
                        .strikethrough(goal.isDone, color: Theme.Colors.secondaryText)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if !goal.deadline.isEmpty {
                        Label(lang.s("goals.deadlinePrefix") + goal.deadline,
                              systemImage: "calendar")
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { editingGoal = goal }
        .contextMenu {
            Button { editingGoal = goal } label: {
                Label(lang.s("goals.edit"), systemImage: "pencil")
            }
            Button { store.toggleDone(api: state.api, goal: goal) } label: {
                Label(lang.s(goal.isDone ? "goals.reopen" : "goals.markDone"),
                      systemImage: goal.isDone ? "arrow.uturn.backward" : "checkmark")
            }
            Button(role: .destructive) {
                store.delete(api: state.api, goal: goal)
            } label: { Label(lang.s("goals.delete"), systemImage: "trash") }
        }
    }

    private var emptyView: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "target")
                .font(.system(size: Theme.Icon.xl, weight: .semibold))
                .foregroundColor(Theme.Colors.secondaryText)
            Text(lang.s("goals.empty"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
            SandyButton(title: lang.s("goals.add"),
                        systemImage: "plus.circle.fill") {
                store.notice = ""
                showAdd = true
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Theme.Spacing.lg)
    }
}

// MARK: - ورقة هدف (إضافة أو تعديل)

/// ورقة بسيطة: نص الهدف + موعد نهائي اختياري. `existing` غير nil ⇒ تعديل (تعبئة
/// مسبقة). تُرسل عبر closure غير متزامن يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
private struct GoalSheet: View {
    let existing: GoalItem?
    let onSubmit: (_ text: String, _ deadline: String) async -> Bool

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var text: String
    @State private var deadline: String
    @State private var submitting = false

    init(existing: GoalItem? = nil,
         onSubmit: @escaping (_ text: String, _ deadline: String) async -> Bool) {
        self.existing = existing
        self.onSubmit = onSubmit
        _text = State(initialValue: existing?.text ?? "")
        _deadline = State(initialValue: existing?.deadline ?? "")
    }

    private var isEditing: Bool { existing != nil }
    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        SandyPopup(title: lang.s(isEditing ? "goals.editTitle" : "goals.addTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                SectionHeader(title: lang.s("goals.sheet.prompt"))
                SandyCard {
                    TextField(lang.s("goals.sheet.placeholder"), text: $text, axis: .vertical)
                        .font(Theme.Typography.body)
                        .lineLimit(2...6)
                }
                SectionHeader(title: lang.s("goals.sheet.deadline"))
                SandyCard {
                    TextField(lang.s("goals.sheet.deadlineHint"), text: $deadline)
                        .font(Theme.Typography.body)
                        .keyboardType(.numbersAndPunctuation)
                        .autocorrectionDisabled()
                }
                SandyButton(title: lang.s(isEditing ? "goals.saveEdit" : "goals.saveNew"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
                .disabled(trimmed.isEmpty)
                .opacity(trimmed.isEmpty ? 0.5 : 1)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard !trimmed.isEmpty, !submitting else { return }
        submitting = true
        Task {
            let ok = await onSubmit(trimmed, deadline.trimmingCharacters(in: .whitespacesAndNewlines))
            submitting = false
            if ok { dismiss() }
        }
    }
}

// MARK: - الموديل

/// هدف واحد كما يرجّعه `/api/goals`. `status` = "active" | "done".
struct GoalItem: Identifiable, Equatable {
    let id: String
    let text: String
    let deadline: String
    let status: String

    var isDone: Bool { status == "done" }
}

// MARK: - الستور

// MARK: - نداءات الباك-إند (أهداف)
