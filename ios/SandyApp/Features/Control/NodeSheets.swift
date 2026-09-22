import SwiftUI

/// شيت الربط، بخطوتين.
///
/// الأولى: كود العلبة (إلزامي) واسم اختياري. لو الوحدة حرّة، **الكود لحاله ما
/// بيربط**: ساندي بتعرض ستّ أرقام ع شاشتها، والخطوة التانية بتطلبهن. هيك صورة
/// للعلبة ما بتكفي حدا ياخد روبوت غيره — لازم يكون واقف قدّامه.
struct NodePairSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    /// (الكود، الاسم?) → النتيجة. بيرمي عند الفشل.
    let onPair: (String, String?) async throws -> PairResult
    /// (الكود، رمز الشاشة، الاسم?). بيرمي عند الفشل.
    let onConfirm: (String, String, String?) async throws -> Void
    /// لما الخطوة الأولى صارت برّا الشيت (شاشة الحساب): الكود جاهز والشيت
    /// بيفتح ع خطوة الرمز مباشرة.
    var initialCode: String = ""
    var startAtPresence: Bool = false

    @State private var code = ""
    @State private var label = ""
    @State private var presence = ""
    @State private var askingPresence = false
    @State private var saving = false
    @State private var notice = ""
    @State private var hint = ""

    private var trimmedCode: String { code.trimmingCharacters(in: .whitespaces) }
    private var digits: String { presence.filter(\.isNumber) }
    private var labelToSend: String? {
        let t = label.trimmingCharacters(in: .whitespaces)
        return t.isEmpty ? nil : t
    }

    var body: some View {
        SandyPopup(title: lang.s("control.node.pairTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                HStack(spacing: Theme.Spacing.sm) {
                    SandyAvatar(size: 36, mood: .happy)
                    Text(lang.s(askingPresence ? "control.node.presenceHeader"
                                               : "control.node.pairHeader"))
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Spacer(minLength: 0)
                }

                if askingPresence {
                    fieldCard(title: lang.s("control.node.presenceField")) {
                        TextField("000000", text: $presence)
                            .font(Theme.Typography.title)
                            .keyboardType(.numberPad)
                            .textContentType(.oneTimeCode)
                            .multilineTextAlignment(.center)
                            .onChange(of: presence) { _, v in
                                // ستّ أرقام بالكتير — الزايد بينقص بدل ما يوصل الخادم.
                                let d = v.filter(\.isNumber)
                                if d.count > 6 || d != v { presence = String(d.prefix(6)) }
                            }
                    }
                    if !hint.isEmpty {
                        Text(hint)
                            .font(Theme.Typography.callout)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                } else {
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
                }

                if !notice.isEmpty {
                    SandyNotice(notice, kind: .gentleWarning)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }

                if askingPresence {
                    SandyButton(title: lang.s("control.node.presenceSubmit"),
                                systemImage: "checkmark.seal",
                                isLoading: saving,
                                fillWidth: true) {
                        confirm()
                    }
                    .disabled(digits.count != 6)
                    .opacity(digits.count != 6 ? 0.6 : 1)

                    Button(lang.s("control.node.presenceResend")) { pair() }
                        .font(Theme.Typography.callout)
                        .foregroundColor(Theme.Colors.accent)
                        .disabled(saving)
                        .frame(maxWidth: .infinity)
                } else {
                    SandyButton(title: lang.s("control.node.pairSubmit"),
                                systemImage: "antenna.radiowaves.left.and.right",
                                isLoading: saving,
                                fillWidth: true) {
                        pair()
                    }
                    .disabled(trimmedCode.isEmpty)
                    .opacity(trimmedCode.isEmpty ? 0.6 : 1)
                }
            }
            .animation(.easeInOut(duration: 0.25), value: notice)
            .animation(.easeInOut(duration: 0.25), value: askingPresence)
        }
        .environment(\.layoutDirection, lang.lang.layoutDirection)
        .onAppear {
            if code.isEmpty && !initialCode.isEmpty { code = initialCode }
            if startAtPresence && !askingPresence {
                askingPresence = true
                hint = lang.s("control.node.presenceHint")
            }
        }
    }

    private func pair() {
        guard !trimmedCode.isEmpty else { return }
        saving = true
        notice = ""
        Task {
            do {
                let res = try await onPair(trimmedCode, labelToSend)
                if res.needsPresence {
                    presence = ""
                    askingPresence = true
                    // الخادم ما قدر يوصّلها: غالبًا مطفية أو مش ع النت. بنقول
                    // هيك بدل ما نخلّيه يستنّى رقم ما رح يطلع.
                    hint = lang.s(res.sent ? "control.node.presenceHint"
                                           : "control.node.presenceNotSent")
                    saving = false
                } else {
                    dismiss()
                }
            } catch {
                if !error.isCancellation { notice = message(for: error) }
                saving = false
            }
        }
    }

    private func confirm() {
        guard digits.count == 6 else { return }
        saving = true
        notice = ""
        Task {
            do {
                try await onConfirm(trimmedCode, digits, labelToSend)
                dismiss()
            } catch {
                if !error.isCancellation { notice = message(for: error) }
                saving = false
            }
        }
    }

    /// كل رمز خطأ بجملته — «الرمز غلط» و«انتهت صلاحيته» بيوجّهوا لخطوتين مختلفتين.
    private func message(for error: Error) -> String {
        switch (error as? APIError)?.code ?? "" {
        case "presence_wrong":    return lang.s("control.node.presenceWrong")
        case "presence_expired",
             "presence_missing",
             "presence_locked":   return lang.s("control.node.presenceExpired")
        case "already_claimed":   return lang.s("control.node.alreadyClaimed")
        case "too_many_attempts": return lang.s("control.node.tooMany")
        default:                  return lang.s("control.node.pairFailed")
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
struct NodeRenameSheet: View {
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
