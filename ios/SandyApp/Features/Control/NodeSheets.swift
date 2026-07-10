import SwiftUI


/// شيت الربط: كود الوحدة (إلزامي) + اسم اختياري. الأخطاء بصوت ساندي.
private struct NodePairSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    /// يستقبل (الكود، الاسم?) ويرمي عند الفشل.
    let onPair: (String, String?) async throws -> Void

    @State private var code = ""
    @State private var label = ""
    @State private var saving = false
    @State private var notice = ""

    private var trimmedCode: String { code.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        SandyPopup(title: lang.s("control.node.pairTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                HStack(spacing: Theme.Spacing.sm) {
                    SandyAvatar(size: 36, mood: .happy)
                    Text(lang.s("control.node.pairHeader"))
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Spacer(minLength: 0)
                }

                fieldCard(title: lang.s("control.node.code")) {
                    TextField(lang.s("control.node.codePlaceholder"), text: $code)
                        .font(Theme.Typography.body)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.characters)
                }

                fieldCard(title: lang.s("control.node.labelField")) {
                    TextField(lang.s("control.node.labelPlaceholder"), text: $label)
                        .font(Theme.Typography.body)
                }

                if !notice.isEmpty {
                    SandyNotice(notice, kind: .gentleWarning)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }

                SandyButton(title: lang.s("control.node.pairSubmit"),
                            systemImage: "antenna.radiowaves.left.and.right",
                            isLoading: saving,
                            fillWidth: true) {
                    pair()
                }
                .disabled(trimmedCode.isEmpty)
                .opacity(trimmedCode.isEmpty ? 0.6 : 1)
            }
            .animation(.easeInOut(duration: 0.25), value: notice)
        }
        .environment(\.layoutDirection, lang.lang.layoutDirection)
    }

    private func pair() {
        guard !trimmedCode.isEmpty else { return }
        saving = true
        notice = ""
        let labelToSend = label.trimmingCharacters(in: .whitespaces)
        Task {
            do {
                try await onPair(trimmedCode, labelToSend.isEmpty ? nil : labelToSend)
                dismiss()
            } catch {
                if !error.isCancellation {
                    notice = lang.s("control.node.pairFailed")
                }
                saving = false
            }
        }
    }

    @ViewBuilder
    private func fieldCard<Content: View>(title: String,
                                          @ViewBuilder content: @escaping () -> Content) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Text(title)
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.secondaryText)
            SandyCard { content() }
        }
    }
}


/// شيت بسيط لإعادة تسمية وحدة مربوطة.
private struct NodeRenameSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    let existing: NodeItem
    let onSave: (String) async throws -> Void

    @State private var label: String
    @State private var saving = false
    @State private var notice = ""

    init(existing: NodeItem, onSave: @escaping (String) async throws -> Void) {
        self.existing = existing
        self.onSave = onSave
        _label = State(initialValue: existing.label)
    }

    private var trimmed: String { label.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        SandyPopup(title: lang.s("control.node.renameTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    Text(lang.s("control.node.labelField"))
                        .font(Theme.Typography.callout)
                        .foregroundColor(Theme.Colors.secondaryText)
                    SandyCard {
                        TextField(lang.s("control.node.labelPlaceholder"), text: $label)
                            .font(Theme.Typography.body)
                    }
                }

                if !notice.isEmpty {
                    SandyNotice(notice, kind: .gentleWarning)
                }

                SandyButton(title: lang.s("control.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: saving,
                            fillWidth: true) {
                    save()
                }
                .disabled(trimmed.isEmpty)
                .opacity(trimmed.isEmpty ? 0.6 : 1)
            }
            .animation(.easeInOut(duration: 0.25), value: notice)
        }
        .environment(\.layoutDirection, lang.lang.layoutDirection)
    }

    private func save() {
        guard !trimmed.isEmpty else { return }
        saving = true
        notice = ""
        Task {
            do {
                try await onSave(trimmed)
                dismiss()
            } catch {
                if !error.isCancellation {
                    notice = lang.s("control.saveFailed")
                }
                saving = false
            }
        }
    }
}
