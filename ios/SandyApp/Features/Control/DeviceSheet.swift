import SwiftUI

/// شيت جهاز (إضافة أو تعديل): اسم + غرفة + نوع تحكّم + طريقة وصل (وحدة/مخرج أو
/// موضوع MQTT خام) + ميتا حسب النوع (خيارات enum، حدّا dimmer) + صف تعليم زر
/// للريموت. `existing` غير nil ⇒ وضع تعديل. الأخطاء بصوت ساندي.
struct DeviceSheet: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    let nodes: [NodeItem]
    let existing: DeviceItem?
    let onSave: (DeviceDraft) async throws -> Void

    @State private var label: String
    @State private var room: String
    @State private var controlType: ControlType
    @State private var transportKind: TransportKind
    @State private var selectedNodeId: String
    @State private var selectedOutput: String
    @State private var topic: String

    // ميتا حسب النوع
    @State private var enumValuesText: String
    @State private var dimmerMin: String
    @State private var dimmerMax: String

    // تعليم زر ريموت (يضاف فورًا للجهاز القائم عند التعديل؛ بالإضافة يُجمَّع بالميتا)
    @State private var irButtons: [String: String]
    @State private var newButtonName: String = ""

    @State private var saving = false
    @State private var notice = ""

    init(nodes: [NodeItem], existing: DeviceItem? = nil,
         onSave: @escaping (DeviceDraft) async throws -> Void) {
        self.nodes = nodes
        self.existing = existing
        self.onSave = onSave
        _label = State(initialValue: existing?.label ?? "")
        _room = State(initialValue: existing?.room ?? "")
        _controlType = State(initialValue: ControlType(rawValue: existing?.controlType ?? "switch") ?? .switch)
        let t = existing?.transport
        _transportKind = State(initialValue: TransportKind(rawValue: t?.kind ?? "node") ?? .node)
        // المخرج/الوحدة الافتراضيان: قيم الجهاز القائم، وإلا أول وحدة/مخرج متاح.
        _selectedNodeId = State(initialValue: t?.nodeId ?? nodes.first?.nodeId ?? "")
        _selectedOutput = State(initialValue: t?.output ?? nodes.first?.outputs.first ?? "")
        _topic = State(initialValue: t?.topic ?? "")
        _enumValuesText = State(initialValue: (existing?.enumValues ?? []).joined(separator: "، "))
        _dimmerMin = State(initialValue: existing.map { String($0.dimmerMin) } ?? "0")
        _dimmerMax = State(initialValue: existing.map { String($0.dimmerMax) } ?? "100")
        _irButtons = State(initialValue: existing?.irButtons ?? [:])
    }

    private var isEditing: Bool { existing != nil }
    private var trimmedLabel: String { label.trimmingCharacters(in: .whitespaces) }

    /// المخارج المتاحة للوحدة المختارة.
    private var outputsForSelectedNode: [String] {
        nodes.first(where: { $0.nodeId == selectedNodeId })?.outputs ?? []
    }

    var body: some View {
        SandyPopup(title: lang.s(isEditing ? "control.device.editTitle" : "control.device.addTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {

                // ترويسة ودّية بصوت ساندي
                HStack(spacing: Theme.Spacing.sm) {
                    SandyAvatar(size: 36, mood: .happy)
                    Text(lang.s("control.device.header"))
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Spacer(minLength: 0)
                }

                // ── الاسم ──
                fieldCard(title: lang.s("control.field.label")) {
                    TextField(lang.s("control.field.labelPlaceholder"), text: $label)
                        .font(Theme.Typography.body)
                }

                // ── الغرفة ──
                fieldCard(title: lang.s("control.field.room")) {
                    TextField(lang.s("control.field.roomPlaceholder"), text: $room)
                        .font(Theme.Typography.body)
                }

                // ── نوع التحكّم ──
                fieldCard(title: lang.s("control.field.type")) {
                    Picker(lang.s("control.field.type"), selection: $controlType) {
                        ForEach(ControlType.allCases) { t in
                            Text(lang.s(t.labelKey)).tag(t)
                        }
                    }
                    .pickerStyle(.menu)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                // ── طريقة الوصل ──
                transportSection

                // ── ميتا حسب النوع ──
                metaSection

                if !notice.isEmpty {
                    SandyNotice(notice, kind: .gentleWarning)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }

                SandyButton(title: lang.s("control.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: saving,
                            fillWidth: true) {
                    save()
                }
                .disabled(!canSave)
                .opacity(canSave ? 1 : 0.6)
            }
            .animation(.easeInOut(duration: 0.25), value: notice)
            .animation(.easeInOut(duration: 0.2), value: controlType)
            .animation(.easeInOut(duration: 0.2), value: transportKind)
        }
        .environment(\.layoutDirection, lang.lang.layoutDirection)
    }

    // ── قسم طريقة الوصل ──
    @ViewBuilder
    private var transportSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Text(lang.s("control.field.transport"))
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.secondaryText)

            Picker("", selection: $transportKind) {
                ForEach(TransportKind.allCases) { k in
                    Text(lang.s(k.labelKey)).tag(k)
                }
            }
            .pickerStyle(.segmented)

            if transportKind == .node {
                if nodes.isEmpty {
                    SandyNotice(lang.s("control.transport.needNode"), kind: .gentleWarning)
                } else {
                    SandyCard {
                        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                            Picker(lang.s("control.transport.pickNode"), selection: $selectedNodeId) {
                                ForEach(nodes) { n in Text(n.label).tag(n.nodeId) }
                            }
                            .pickerStyle(.menu)
                            .onChange(of: selectedNodeId) { _, _ in
                                // عند تبديل الوحدة، نختار أول مخرج لها.
                                selectedOutput = outputsForSelectedNode.first ?? ""
                            }
                            if !outputsForSelectedNode.isEmpty {
                                Picker(lang.s("control.transport.pickOutput"), selection: $selectedOutput) {
                                    ForEach(outputsForSelectedNode, id: \.self) { o in Text(o).tag(o) }
                                }
                                .pickerStyle(.menu)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            } else {
                SandyCard {
                    TextField(lang.s("control.transport.topicPlaceholder"), text: $topic)
                        .font(Theme.Typography.body)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                }
            }
        }
    }

    // ── قسم الميتا حسب النوع ──
    @ViewBuilder
    private var metaSection: some View {
        switch controlType {
        case .enum:
            fieldCard(title: lang.s("control.meta.enumValues")) {
                TextField(lang.s("control.meta.enumPlaceholder"), text: $enumValuesText, axis: .vertical)
                    .font(Theme.Typography.body)
                    .lineLimit(1...3)
            }
        case .dimmer:
            HStack(spacing: Theme.Spacing.md) {
                fieldCard(title: lang.s("control.meta.dimmerMin")) {
                    TextField("0", text: $dimmerMin)
                        .keyboardType(.numberPad)
                        .font(Theme.Typography.body)
                }
                fieldCard(title: lang.s("control.meta.dimmerMax")) {
                    TextField("100", text: $dimmerMax)
                        .keyboardType(.numberPad)
                        .font(Theme.Typography.body)
                }
            }
        case .ir:
            irLearnSection
        default:
            EmptyView()
        }
    }

    // ── صف تعليم زر ريموت (بسيط: اسم الزر فقط؛ التقاط الكود يجي مع الوحدة لاحقًا) ──
    @ViewBuilder
    private var irLearnSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Text(lang.s("control.ir.buttons"))
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.secondaryText)

            // الأزرار المحفوظة (لكل واحد زر حذف).
            if irButtons.isEmpty {
                Text(lang.s("control.ir.noButtons"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.tertiaryText)
            } else {
                ForEach(irButtons.keys.sorted(), id: \.self) { name in
                    HStack {
                        Image(systemName: "dot.radiowaves.left.and.right")
                            .foregroundColor(Theme.Colors.accent)
                        Text(name)
                            .font(Theme.Typography.body)
                            .foregroundColor(Theme.Colors.primaryText)
                        Spacer(minLength: 0)
                        Button {
                            irButtons.removeValue(forKey: name)
                        } label: {
                            Image(systemName: "trash")
                                .foregroundColor(Theme.Colors.danger)
                        }
                        .buttonStyle(.plain)
                    }
                    .padding(.vertical, Theme.Spacing.xs)
                }
            }

            Text(lang.s("control.ir.learnHint"))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.tertiaryText)
                .fixedSize(horizontal: false, vertical: true)

            SandyCard {
                HStack(spacing: Theme.Spacing.sm) {
                    TextField(lang.s("control.ir.learnPlaceholder"), text: $newButtonName)
                        .font(Theme.Typography.body)
                    Button {
                        addButton()
                    } label: {
                        Image(systemName: "plus.circle.fill")
                            .font(.title3)
                            .foregroundColor(Theme.Colors.accent)
                    }
                    .buttonStyle(.plain)
                    .disabled(newButtonName.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }

    private func addButton() {
        let n = newButtonName.trimmingCharacters(in: .whitespaces)
        guard !n.isEmpty else { return }
        // كود فاضي مبدئيًّا — التقاط الكود الحقيقي يجي مع تحديث الوحدة لاحقًا.
        if irButtons[n] == nil { irButtons[n] = "" }
        newButtonName = ""
        // عند التعديل على جهاز قائم، نسجّل الزر بالباك-إند مباشرة كذلك.
        if let existing {
            Task { try? await state.api.irLearn(name: existing.name, button: n, code: "") }
        }
    }

    // ── جاهزية الحفظ ──
    private var canSave: Bool {
        guard !trimmedLabel.isEmpty else { return false }
        switch transportKind {
        case .node:
            return !selectedNodeId.isEmpty && !selectedOutput.isEmpty
        case .mqtt:
            return !topic.trimmingCharacters(in: .whitespaces).isEmpty
        }
    }

    // ── بناء الميتا حسب النوع ──
    private func buildMeta() -> [String: Any] {
        switch controlType {
        case .enum:
            // نفصل على الفاصلة العربية أو اللاتينية، ونزيل الفراغات والفاضي.
            let values = enumValuesText
                .split(whereSeparator: { $0 == "،" || $0 == "," })
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
            return values.isEmpty ? [:] : ["values": values]
        case .dimmer:
            let lo = Int(dimmerMin.trimmingCharacters(in: .whitespaces)) ?? 0
            let hi = Int(dimmerMax.trimmingCharacters(in: .whitespaces)) ?? 100
            return ["min": lo, "max": max(hi, lo + 1)]
        case .ir:
            return irButtons.isEmpty ? [:] : ["buttons": irButtons]
        default:
            return [:]
        }
    }

    /// معرّف ثابت من التسمية (يبقى مستقرًّا) — عند التعديل نُبقي معرّف الجهاز القائم.
    private func makeName() -> String {
        if let existing { return existing.name }
        // الباك إند يقبل [a-z0-9_] فقط: أي محرف غير لاتيني/رقمي (مسافة، عربي…)
        // يصير "_"، ثم نطوي التكرار ونقصّ الأطراف. تسمية عربية تؤول إلى "device".
        let mapped = String(trimmedLabel.lowercased().map {
            ($0.isASCII && ($0.isLetter || $0.isNumber)) ? $0 : "_"
        })
        var slug = mapped
        while slug.contains("__") { slug = slug.replacingOccurrences(of: "__", with: "_") }
        slug = slug.trimmingCharacters(in: CharacterSet(charactersIn: "_"))
        if slug.isEmpty { slug = "device" }
        slug = String(slug.prefix(30))
        // لاحقة قصيرة تتفادى التصادم.
        return "\(slug)_\(Int(Date().timeIntervalSince1970) % 100000)"
    }

    private func buildTransport() -> DeviceTransport {
        switch transportKind {
        case .node:
            return DeviceTransport(kind: "node", topic: "",
                                   nodeId: selectedNodeId, output: selectedOutput)
        case .mqtt:
            return DeviceTransport(kind: "mqtt",
                                   topic: topic.trimmingCharacters(in: .whitespaces),
                                   nodeId: "", output: "")
        }
    }

    private func save() {
        guard canSave else { return }
        saving = true
        notice = ""
        let draft = DeviceDraft(name: makeName(),
                                label: trimmedLabel,
                                room: room.trimmingCharacters(in: .whitespaces),
                                controlType: controlType.rawValue,
                                transport: buildTransport(),
                                meta: buildMeta())
        Task {
            do {
                try await onSave(draft)
                dismiss()
            } catch {
                if !error.isCancellation {
                    notice = lang.s("control.saveFailed")
                }
                saving = false
            }
        }
    }

    /// بطاقة حقل صغيرة بعنوان فوقها — توحّد شكل الحقول.
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
