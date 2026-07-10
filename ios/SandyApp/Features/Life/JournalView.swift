import SwiftUI


/// شاشة اليوميات — تعرض التدوينات مع شيت إضافة مريح (محرّر متعدّد الأسطر).
struct JournalView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    /// مصدر الحقيقة لليوميات (يملك البيانات + الجلب + الإضافة، مستقل عن الشاشة).
    @StateObject private var store = JournalStore()
    @State private var showAdd = false
    /// الخاطرة الجاري تعديلها (nil = ما في ورقة تعديل مفتوحة).
    @State private var editingEntry: JournalEntry?

    var body: some View {
        // الخلفية موحّدة على مستوى MainTabView — لا نكرّرها هون (طبقة مهدورة).
        ZStack {
            VStack(spacing: 0) {
                if store.demo { DemoBanner() }

                if !store.error.isEmpty {
                    SandyNotice(store.error, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                SandyButton(title: lang.s("life.journal.add"), systemImage: "square.and.pencil", fillWidth: true) {
                    showAdd = true
                }
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.vertical, Theme.Spacing.md)
                .disabled(store.demo)
                .opacity(store.demo ? 0.5 : 1)

                if store.loading && store.entries.isEmpty {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else if store.entries.isEmpty {
                    LivelyEmptyState(
                        line: lang.s("life.journal.empty"),
                        mood: .happy)
                    Spacer()
                } else {
                    List {
                        ForEach(store.entries) { entry in
                            entryRow(entry)
                                .listRowBackground(Color.clear)
                                .listRowSeparator(.hidden)
                                .listRowInsets(EdgeInsets(top: Theme.Spacing.xs, leading: Theme.Spacing.md,
                                                          bottom: Theme.Spacing.xs, trailing: Theme.Spacing.md))
                                .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                    if !store.demo {
                                        Button(role: .destructive) {
                                            store.delete(api: state.api, entry: entry)
                                        } label: { Label(lang.s("life.journal.delete"), systemImage: "trash") }
                                    }
                                }
                                .swipeActions(edge: .leading) {
                                    if !store.demo {
                                        Button { editingEntry = entry } label: {
                                            Label(lang.s("life.journal.edit"), systemImage: "pencil")
                                        }
                                        .tint(Theme.Colors.accent)
                                    }
                                }
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.entries.count)
                }
            }
        }
        .navigationTitle(lang.s("life.journal"))
        .fullScreenCover(isPresented: $showAdd) {
            JournalSheet { text in
                try await store.add(api: state.api, text: text)
            }
        }
        .fullScreenCover(item: $editingEntry) { entry in
            JournalSheet(existing: entry) { text in
                try await store.update(api: state.api, id: entry.id, text: text)
            }
        }
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
    }

    @ViewBuilder
    private func entryRow(_ entry: JournalEntry) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            HStack(spacing: Theme.Spacing.xs) {
                Image(systemName: "quote.opening")
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondary)
                if !entry.date.isEmpty {
                    Text(entry.date)
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.tertiaryText)
                }
                Spacer(minLength: 0)
            }
            Text(entry.text)
                .font(Theme.Typography.body)
                .foregroundColor(Theme.Colors.primaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
        .sandyCard()
        .contentShape(Rectangle())
        .onTapGesture { if !store.demo { editingEntry = entry } }
        .contextMenu {
            if !store.demo {
                Button { editingEntry = entry } label: {
                    Label(lang.s("life.journal.edit"), systemImage: "pencil")
                }
                Button(role: .destructive) {
                    store.delete(api: state.api, entry: entry)
                } label: { Label(lang.s("life.journal.delete"), systemImage: "trash") }
            }
        }
    }

}


/// شيت خاطرة (إضافة أو تعديل): محرّر متعدّد الأسطر مريح + عدّاد أحرف خفيف.
struct JournalSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var lang: LanguageManager
    /// الخاطرة القائمة عند التعديل (nil = إضافة جديدة).
    let existing: JournalEntry?
    /// يستقبل النص ويرمي عند الفشل.
    let onSave: (String) async throws -> Void

    @State private var text: String
    @State private var saving = false
    @State private var error = ""

    init(existing: JournalEntry? = nil, onSave: @escaping (String) async throws -> Void) {
        self.existing = existing
        self.onSave = onSave
        _text = State(initialValue: existing?.text ?? "")
    }

    private var isEditing: Bool { existing != nil }
    private var trimmed: String { text.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        SandyPopup(title: lang.s(isEditing ? "life.journal.sheet.editTitle" : "life.journal.sheet.title")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                SectionHeader(title: lang.s("life.journal.sheet.section"))
                SandyCard {
                    TextField(lang.s("life.journal.sheet.placeholder"), text: $text, axis: .vertical)
                        .lineLimit(5...12)
                        .font(.body)
                }
                HStack {
                    Spacer(minLength: 0)
                    Text(String(format: lang.s("life.journal.sheet.charCount"), "\(trimmed.count)"))
                        .font(.caption2)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
                if !error.isEmpty {
                    SandyNotice(error, kind: .gentleWarning)
                }
                SandyButton(title: lang.s("common.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: saving,
                            fillWidth: true) {
                    save()
                }
                .disabled(trimmed.isEmpty)
                .opacity(trimmed.isEmpty ? 0.5 : 1)
            }
            .animation(.easeInOut(duration: 0.25), value: error)
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard !trimmed.isEmpty else { return }
        saving = true
        withAnimation { error = "" }
        Task {
            do {
                try await onSave(trimmed)
                dismiss()
            } catch {
                withAnimation { self.error = lang.s("life.journal.saveError") }
            }
            saving = false
        }
    }
}
