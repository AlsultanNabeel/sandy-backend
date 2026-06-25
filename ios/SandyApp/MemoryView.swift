import SwiftUI

/// تبويب الذاكرة — يعرض المعلومات الحقيقية اللي ساندي متذكّراها عنك (`sandy_facts`)
/// عبر `/api/memory`، ويسمح بحذف أي وحدة. يستثني ذاكرة المنظومة الآلية (ملخّصات
/// المحادثات) عمدًا. نمط الستور المعتمد: الجلب بمهمة يملكها الستور.
struct MemoryView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = MemoryStore()
    @State private var showAdd = false
    /// المعلومة الجاري تعديلها (nil = ما في ورقة تعديل مفتوحة).
    @State private var editingFact: MemoryFact?

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
        .navigationTitle(lang.s("tabs.memory"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                SandyButton(title: lang.s("memory.add"),
                            systemImage: "plus.circle.fill",
                            style: .secondary) {
                    store.notice = ""
                    showAdd = true
                }
            }
        }
        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.facts.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .sheet(isPresented: $showAdd) {
            MemorySheet { text in await store.add(api: state.api, text: text) }
        }
        .sheet(item: $editingFact) { fact in
            MemorySheet(existing: fact) { text in
                await store.update(api: state.api, id: fact.id, text: text)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if store.facts.isEmpty && !store.loading {
            emptyView
        } else {
            List {
                // المقدّمة صف غير قابل للسحب يبقى أعلى القائمة.
                header
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: Theme.Spacing.sm, leading: Theme.Spacing.md,
                                              bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                ForEach(store.facts) { fact in
                    factCard(fact)
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                  bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            Button(role: .destructive) {
                                store.delete(api: state.api, fact: fact)
                            } label: { Label(lang.s("memory.delete"), systemImage: "trash") }
                        }
                        .swipeActions(edge: .leading) {
                            Button { editingFact = fact } label: {
                                Label(lang.s("memory.edit"), systemImage: "pencil")
                            }
                            .tint(Theme.Colors.accent)
                        }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
    }

    private var header: some View {
        Text(lang.s("memory.intro"))
            .font(Theme.Typography.subheadline)
            .foregroundColor(Theme.Colors.secondaryText)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func factCard(_ fact: MemoryFact) -> some View {
        SandyCard {
            HStack(alignment: .top, spacing: Theme.Spacing.md) {
                Image(systemName: "sparkle")
                    .font(.caption)
                    .foregroundColor(Theme.Colors.accent)
                    .padding(.top, 3)
                Text(fact.text)
                    .font(Theme.Typography.body)
                    .foregroundColor(Theme.Colors.primaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { editingFact = fact }
        .contextMenu {
            Button { editingFact = fact } label: {
                Label(lang.s("memory.edit"), systemImage: "pencil")
            }
            Button(role: .destructive) {
                store.delete(api: state.api, fact: fact)
            } label: { Label(lang.s("memory.delete"), systemImage: "trash") }
        }
    }

    private var emptyView: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "brain.head.profile")
                .font(.system(size: 44))
                .foregroundColor(Theme.Colors.accent.opacity(0.5))
            Text(lang.s("memory.empty"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
            SandyButton(title: lang.s("memory.add"),
                        systemImage: "plus.circle.fill") {
                store.notice = ""
                showAdd = true
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Theme.Spacing.lg)
    }
}

// MARK: - ورقة معلومة (إضافة أو تعديل)

/// ورقة بسيطة: محرّر نص متعدّد الأسطر لمعلومة يتذكّرها ساندي عنك. `existing` غير
/// nil ⇒ تعديل (تعبئة مسبقة). تُرسل عبر closure غير متزامن يرجّع نجاح/فشل.
private struct MemorySheet: View {
    let existing: MemoryFact?
    let onSubmit: (_ text: String) async -> Bool

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var text: String
    @State private var submitting = false

    init(existing: MemoryFact? = nil, onSubmit: @escaping (_ text: String) async -> Bool) {
        self.existing = existing
        self.onSubmit = onSubmit
        _text = State(initialValue: existing?.text ?? "")
    }

    private var isEditing: Bool { existing != nil }
    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        NavigationStack {
            ZStack {
                SandyBackground()
                ScrollView {
                    VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                        SectionHeader(title: lang.s("memory.sheet.prompt"))
                        SandyCard {
                            TextField(lang.s("memory.sheet.placeholder"), text: $text, axis: .vertical)
                                .font(Theme.Typography.body)
                                .lineLimit(3...8)
                        }
                        SandyButton(title: lang.s(isEditing ? "memory.saveEdit" : "memory.saveNew"),
                                    systemImage: "checkmark.circle.fill",
                                    isLoading: submitting,
                                    fillWidth: true) {
                            save()
                        }
                        .disabled(trimmed.isEmpty)
                        .opacity(trimmed.isEmpty ? 0.5 : 1)
                    }
                    .padding(Theme.Spacing.md)
                }
            }
            .navigationTitle(lang.s(isEditing ? "memory.editTitle" : "memory.addTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("common.cancel")) { dismiss() }
                }
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard !trimmed.isEmpty, !submitting else { return }
        submitting = true
        Task {
            let ok = await onSubmit(trimmed)
            submitting = false
            if ok { dismiss() }
        }
    }
}

// MARK: - الستور

@MainActor
final class MemoryStore: ObservableObject {
    @Published var facts: [MemoryFact] = []
    @Published var loading = false
    @Published var notice = ""

    private var loadTask: Task<Void, Never>?

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                facts = try await api.getMemory()
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("memory.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// إضافة معلومة ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, text: String) async -> Bool {
        do {
            try await api.addMemory(text: text)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("memory.errorAdd")
            return false
        }
    }

    /// تعديل نص معلومة ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة.
    func update(api: APIClient, id: String, text: String) async -> Bool {
        do {
            try await api.updateMemory(id: id, text: text)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("memory.errorEdit")
            return false
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, fact: MemoryFact) {
        guard let idx = facts.firstIndex(where: { $0.id == fact.id }) else { return }
        facts.remove(at: idx)
        Task { @MainActor in
            do {
                try await api.deleteMemory(id: fact.id)
            } catch {
                facts.insert(fact, at: min(idx, facts.count))
                notice = LanguageManager.shared.s("memory.errorDelete")
            }
        }
    }
}
