import SwiftUI

/// Quick add without talking to Sandy: pick a kind, type, save. One window that turns
/// from the chooser into the form. Every kind lands in one of the three blocks.
struct QuickAddSheet: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject private var kinds = KindsStore.shared
    @State private var chosen: BlockKind?

    /// The kinds offered, in this order; labels and icons come from the kinds table.
    private static let offered: [(String, BlockType)] = [
        ("tasks", .list), ("shopping", .list), ("reminder", .schedule), ("expense", .log),
        ("journal", .log), ("habits", .list), ("message_to_future_self", .schedule),
    ]

    var body: some View {
        Group {
            if let chosen {
                QuickAddForm(kind: chosen)
            } else {
                chooser
            }
        }
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: chosen)
        .task { await kinds.load(api: state.api) }
    }

    private var chooser: some View {
        SandyPopup(title: lang.s("blocks.quickAdd")) {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: Theme.Spacing.md),
                                GridItem(.flexible(), spacing: Theme.Spacing.md)],
                      spacing: Theme.Spacing.md) {
                ForEach(Self.offered.compactMap { kinds.kind($0.0, $0.1) }) { k in
                    Button { chosen = k } label: {
                        VStack(spacing: Theme.Spacing.sm) {
                            Image(systemName: k.icon)
                                .font(.system(size: Theme.Icon.lg, weight: .semibold))
                                .foregroundColor(Theme.Colors.accent)
                            Text(k.label(lang.lang))
                                .font(Theme.Typography.subheadline)
                                .foregroundColor(Theme.Colors.primaryText)
                                .lineLimit(1)
                                .minimumScaleFactor(0.8)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Theme.Spacing.md)
                        .sandyCard()
                    }
                    .liquidGlassPress()
                }
            }
        }
    }
}

private struct QuickAddForm: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let kind: BlockKind
    @State private var text = ""
    @State private var date = Date().addingTimeInterval(3600)
    @State private var amount = ""
    @State private var saving = false
    @State private var failed = false

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        SandyPopup(title: kind.label(lang.lang)) {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                TextField(lang.s("blocks.entryPlaceholder"), text: $text, axis: .vertical)
                    .padding(Theme.Spacing.sm)
                    .liquidGlass(cornerRadius: Theme.Radius.control)
                if kind.block == .schedule {
                    DatePicker(lang.s("blocks.when"), selection: $date, in: Date()...)
                }
                if kind.name == "expense" {
                    TextField(lang.s("blocks.amount"), text: $amount)
                        .keyboardType(.decimalPad)
                        .padding(Theme.Spacing.sm)
                        .liquidGlass(cornerRadius: Theme.Radius.control)
                }
                if failed {
                    SandyNotice(lang.s("blocks.errorSave"), kind: .gentleWarning)
                }
                SandyButton(title: lang.s("blocks.save"), systemImage: "checkmark.circle.fill",
                            isLoading: saving, fillWidth: true) { save() }
                    .disabled(trimmed.isEmpty || saving)
            }
        }
    }

    private func save() {
        saving = true
        failed = false
        Task {
            do {
                switch kind.block {
                case .list:
                    try await state.api.addItem(list: kind.name, text: trimmed)
                case .schedule:
                    try await state.api.addSchedule(kind: kind.name, text: trimmed, at: date)
                case .log:
                    let value = Double(amount.replacingOccurrences(of: ",", with: "."))
                    try await state.api.addEntry(kind: kind.name, text: trimmed,
                                                 data: value.map { ["amount": .number($0)] })
                }
                dismiss()
            } catch {
                failed = true
            }
            saving = false
        }
    }
}
