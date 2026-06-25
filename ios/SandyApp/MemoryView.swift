import SwiftUI

/// تبويب الذاكرة — يعرض المعلومات الحقيقية اللي ساندي متذكّراها عنك (`sandy_facts`)
/// عبر `/api/memory`، ويسمح بحذف أي وحدة. يستثني ذاكرة المنظومة الآلية (ملخّصات
/// المحادثات) عمدًا. نمط الستور المعتمد: الجلب بمهمة يملكها الستور.
struct MemoryView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = MemoryStore()

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
        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.facts.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
    }

    @ViewBuilder
    private var content: some View {
        if store.facts.isEmpty && !store.loading {
            emptyView
        } else {
            ScrollView {
                VStack(spacing: Theme.Spacing.md) {
                    header
                    ForEach(store.facts) { fact in
                        factCard(fact)
                    }
                }
                .padding(Theme.Spacing.md)
                .padding(.bottom, Theme.Spacing.xxl + Theme.Spacing.xl)
            }
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
                Button {
                    store.delete(api: state.api, fact: fact)
                } label: {
                    Image(systemName: "trash")
                        .font(.caption)
                        .foregroundColor(Theme.Colors.danger)
                }
                .buttonStyle(.plain)
            }
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
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Theme.Spacing.lg)
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
