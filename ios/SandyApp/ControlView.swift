import SwiftUI

/// شاشة التحكّم بالبيت — نظام الإضافات المعتمد على البيانات: تربط وحدة ساندي،
/// تضيف أجهزة حقيقية، وتتحكّم فيها. كل جهاز يرسم أداة التحكّم المناسبة لنوعه
/// (مفتاح/إضاءة/ستارة/وسائط/خيارات/ريموت). نفس وصفة ساندي: ستور يملك الحقيقة،
/// تحديث متفائل ثم مصالحة، وأخطاء بصوت ساندي عبر SandyNotice.
struct ControlView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store = DevicesStore()

    @State private var showAddDevice = false
    @State private var editingDevice: DeviceItem?
    @State private var showPairNode = false
    @State private var renamingNode: NodeItem?

    var body: some View {
        ZStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.section) {
                    if store.demo { DemoBanner() }

                    if !store.notice.isEmpty {
                        SandyNotice(store.notice, kind: .gentleWarning)
                            .transition(.move(edge: .top).combined(with: .opacity))
                    }

                    content

                    // مساحة سفلية حتى ما يغطّي الزرّ العائم آخر بطاقة.
                    Color.clear.frame(height: Theme.Spacing.xxl + Theme.Spacing.xl)
                }
                .padding(Theme.Spacing.md)
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            // زر إضافة جهاز — عائم بالأسفل (يظهر فقط لمّا في وحدة مربوطة وبيانات حقيقية).
            if !store.demo && !store.nodes.isEmpty {
                VStack {
                    Spacer()
                    SandyButton(title: lang.s("control.device.add"),
                                systemImage: "plus.circle.fill",
                                fillWidth: true) {
                        showAddDevice = true
                    }
                    .padding(.horizontal, Theme.Spacing.lg)
                    .padding(.bottom, Theme.Spacing.lg)
                }
            }
        }
        .navigationTitle(lang.s("control.title"))
        .fullScreenCover(isPresented: $showAddDevice) {
            DeviceSheet(nodes: store.nodes) { draft in
                try await store.add(api: state.api, draft: draft)
            }
            .environmentObject(state)
            .environmentObject(lang)
        }
        .fullScreenCover(item: $editingDevice) { device in
            DeviceSheet(nodes: store.nodes, existing: device) { draft in
                try await store.update(api: state.api, device: device, draft: draft)
            }
            .environmentObject(state)
            .environmentObject(lang)
        }
        .fullScreenCover(isPresented: $showPairNode) {
            NodePairSheet { code, label in
                try await store.pair(api: state.api, code: code, label: label)
            }
            .environmentObject(lang)
        }
        .fullScreenCover(item: $renamingNode) { node in
            NodeRenameSheet(existing: node) { label in
                try await store.rename(api: state.api, node: node, label: label)
            }
            .environmentObject(lang)
        }
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .animation(.spring(response: 0.45, dampingFraction: 0.82), value: store.devices.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
    }

    // ── المحتوى: تحميل / فاضي / أقسام ──────────────────────────────────────
    @ViewBuilder
    private var content: some View {
        if store.loading && store.devices.isEmpty && store.nodes.isEmpty {
            loadingState
        } else {
            devicesSection
            nodesSection
        }
    }

    private var loadingState: some View {
        VStack(spacing: Theme.Spacing.md) {
            ProgressView().tint(Theme.Colors.accent)
            Text(lang.s("control.loading"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Spacing.xxl)
    }

    // MARK: - قسم الأجهزة (مجموعة حسب الغرفة)

    @ViewBuilder
    private var devicesSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            SectionHeader(title: lang.s("control.section.devices"))

            if store.devices.isEmpty {
                deviceEmptyState
            } else {
                ForEach(store.roomGroups, id: \.room) { group in
                    VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                        Text(group.room.isEmpty ? lang.s("control.noRoom") : group.room)
                            .font(Theme.Typography.callout)
                            .foregroundColor(Theme.Colors.secondaryText)
                        ForEach(group.devices) { device in
                            DeviceCard(device: device, store: store,
                                       onEdit: { editingDevice = device })
                        }
                    }
                }
            }
        }
    }

    private var deviceEmptyState: some View {
        VStack(spacing: Theme.Spacing.md) {
            SandyAvatar(size: 64, mood: .happy)
            Text(lang.s("control.devices.empty.title"))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
            Text(lang.s("control.devices.empty.hint"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Spacing.lg)
    }

    // MARK: - قسم وحدات ساندي

    @ViewBuilder
    private var nodesSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            HStack {
                SectionHeader(title: lang.s("control.section.nodes"))
                Spacer(minLength: 0)
                if !store.demo {
                    Button {
                        showPairNode = true
                    } label: {
                        HStack(spacing: Theme.Spacing.xs) {
                            Image(systemName: "plus")
                                .font(.system(size: Theme.Icon.sm, weight: .bold))
                            Text(lang.s("control.node.pair"))
                                .font(Theme.Typography.callout)
                        }
                        .foregroundColor(Theme.Colors.accent)
                    }
                    .buttonStyle(.plain)
                }
            }

            if store.nodes.isEmpty {
                nodeEmptyState
            } else {
                ForEach(store.nodes) { node in
                    NodeCard(node: node, store: store,
                             onRename: { renamingNode = node })
                }
            }
        }
    }

    private var nodeEmptyState: some View {
        VStack(spacing: Theme.Spacing.md) {
            SandyAvatar(size: 56, mood: .soft)
            Text(lang.s("control.nodes.empty.title"))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
            Text(lang.s("control.nodes.empty.hint"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            if !store.demo {
                SandyButton(title: lang.s("control.node.pair"),
                            systemImage: "antenna.radiowaves.left.and.right") {
                    showPairNode = true
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Spacing.lg)
    }
}

// ─────────────────────────────────────────────────────────────────────────
// MARK: - بطاقة جهاز (أداة التحكّم حسب النوع)

/// بطاقة جهاز واحد: ترويسة (اسم + غرفة + حالة الاتصال) + أداة التحكّم المناسبة
/// لنوعه. النقر المطوّل/القائمة السياقية تفتح التعديل أو الحذف.
private struct DeviceCard: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    let device: DeviceItem
    @ObservedObject var store: DevicesStore
    let onEdit: () -> Void

    /// قيمة شريط الإضاءة المحلّية (نحرّكها بسلاسة قبل ما نرسل عند الإفلات).
    @State private var sliderValue: Double = 0
    /// تعلّم زر أشعة جديد (الاسم + فتح التنبيه).
    @State private var showLearn = false
    @State private var learnButtonName = ""

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            header
            controlWidget
        }
        .sandyCard()
        .contextMenu {
            if !store.demo {
                Button { onEdit() } label: {
                    Label(lang.s("control.device.edit"), systemImage: "pencil")
                }
                Button(role: .destructive) {
                    store.delete(api: state.api, device: device)
                } label: { Label(lang.s("control.device.delete"), systemImage: "trash") }
            }
        }
        .onAppear { sliderValue = Double(Int(device.state) ?? device.dimmerMin) }
    }

    private var header: some View {
        HStack(spacing: Theme.Spacing.md) {
            Image(systemName: iconForType(device.controlType))
                .font(.system(size: Theme.Icon.md, weight: .semibold))
                .foregroundColor(Theme.Colors.accent)
                .frame(width: 38, height: 38)
                .background(Theme.Colors.accent.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))

            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(device.label)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                onlineLabel
            }
            Spacer(minLength: 0)
        }
    }

    private var onlineLabel: some View {
        HStack(spacing: Theme.Spacing.xs) {
            Circle()
                .fill(device.online ? Theme.Colors.success : Theme.Colors.tertiaryText)
                .frame(width: 7, height: 7)
            Text(device.online ? lang.s("control.online") : lang.s("control.offline"))
                .font(Theme.Typography.caption)
                .foregroundColor(device.online ? Theme.Colors.success : Theme.Colors.tertiaryText)
        }
    }

    // ── أداة التحكّم حسب النوع ──
    @ViewBuilder
    private var controlWidget: some View {
        switch device.controlType {
        case "switch":  switchWidget
        case "dimmer":  dimmerWidget
        case "cover":   coverWidget
        case "media":   mediaWidget
        case "enum":    enumWidget
        case "ir":      irWidget
        default:        switchWidget
        }
    }

    // switch — تبديل on/off.
    private var switchWidget: some View {
        let isOn = device.state == "on"
        return Toggle(isOn: Binding(
            get: { isOn },
            set: { store.control(api: state.api, device: device, action: $0 ? "on" : "off") }
        )) {
            Text(isOn ? lang.s("control.action.on") : lang.s("control.action.off"))
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.secondaryText)
        }
        .tint(Theme.Colors.accent)
        .disabled(store.demo)
    }

    // dimmer — تبديل on/off + شريط قيمة (يُرسل set عند الإفلات).
    private var dimmerWidget: some View {
        let isOn = device.state != "off" && device.state != "0" && !device.state.isEmpty
        return VStack(spacing: Theme.Spacing.sm) {
            Toggle(isOn: Binding(
                get: { isOn },
                set: { store.control(api: state.api, device: device, action: $0 ? "on" : "off") }
            )) {
                Text(isOn ? lang.s("control.action.on") : lang.s("control.action.off"))
                    .font(Theme.Typography.callout)
                    .foregroundColor(Theme.Colors.secondaryText)
            }
            .tint(Theme.Colors.accent)
            .disabled(store.demo)

            HStack(spacing: Theme.Spacing.sm) {
                Text(lang.s("control.dimmer.level"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.tertiaryText)
                Slider(value: $sliderValue,
                       in: Double(device.dimmerMin)...Double(device.dimmerMax),
                       step: 1,
                       onEditingChanged: { editing in
                           // نرسل فقط عند انتهاء السحب — تفادي وابل طلبات.
                           if !editing {
                               store.control(api: state.api, device: device,
                                             action: "set", value: String(Int(sliderValue)))
                           }
                       })
                    .tint(Theme.Colors.accent)
                    .disabled(store.demo)
                Text("\(Int(sliderValue))")
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .monospacedDigit()
                    .frame(width: 34, alignment: .trailing)
            }
        }
    }

    // cover — افتح/سكّر/وقّف.
    private var coverWidget: some View {
        HStack(spacing: Theme.Spacing.sm) {
            controlButton(lang.s("control.action.open"), "arrow.up.to.line") {
                store.control(api: state.api, device: device, action: "open")
            }
            controlButton(lang.s("control.action.stop"), "stop.fill") {
                store.control(api: state.api, device: device, action: "stop")
            }
            controlButton(lang.s("control.action.close"), "arrow.down.to.line") {
                store.control(api: state.api, device: device, action: "close")
            }
        }
    }

    // media — شغّل/ثبّت/طفّي.
    private var mediaWidget: some View {
        HStack(spacing: Theme.Spacing.sm) {
            controlButton(lang.s("control.action.play"), "play.fill") {
                store.control(api: state.api, device: device, action: "on")
            }
            controlButton(lang.s("control.action.pause"), "pause.fill") {
                store.control(api: state.api, device: device, action: "pause")
            }
            controlButton(lang.s("control.action.off"), "power") {
                store.control(api: state.api, device: device, action: "off")
            }
        }
    }

    // enum — قائمة بخيارات meta.values (set + القيمة).
    @ViewBuilder
    private var enumWidget: some View {
        if device.enumValues.isEmpty {
            EmptyView()
        } else {
            // segmented لو الخيارات قليلة، وإلا قائمة منسدلة.
            Picker("", selection: Binding(
                get: { device.state.isEmpty ? (device.enumValues.first ?? "") : device.state },
                set: { store.control(api: state.api, device: device, action: "set", value: $0) }
            )) {
                ForEach(device.enumValues, id: \.self) { v in
                    Text(v).tag(v)
                }
            }
            .pickerStyle(device.enumValues.count <= 3 ? .segmented : .menu)
            .disabled(store.demo)
        }
    }

    // ir — أزرار من meta.buttons (send + اسم الزر) + تعلّم زر جديد عبر الوحدة.
    @ViewBuilder
    private var irWidget: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            if device.irButtonNames.isEmpty {
                Text(lang.s("control.ir.noButtons"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.tertiaryText)
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: Theme.Spacing.sm)],
                          spacing: Theme.Spacing.sm) {
                    ForEach(device.irButtonNames, id: \.self) { name in
                        controlButton(name, "dot.radiowaves.left.and.right") {
                            store.control(api: state.api, device: device, action: "send", value: name)
                        }
                    }
                }
            }

            if store.learning {
                HStack(spacing: Theme.Spacing.sm) {
                    ProgressView().tint(Theme.Colors.accent)
                    Text(lang.s("control.ir.learning"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
            } else if !store.demo {
                Button { showLearn = true } label: {
                    Label(lang.s("control.ir.learnNew"), systemImage: "plus.circle")
                        .font(Theme.Typography.callout)
                        .foregroundColor(Theme.Colors.accent)
                }
                .buttonStyle(.plain)
            }
        }
        .alert(lang.s("control.ir.learnNew"), isPresented: $showLearn) {
            TextField(lang.s("control.ir.learnPlaceholder"), text: $learnButtonName)
            Button(lang.s("control.ir.learnStart")) {
                store.learnIR(api: state.api, device: device, button: learnButtonName)
                learnButtonName = ""
            }
            Button(lang.s("common.cancel"), role: .cancel) { learnButtonName = "" }
        } message: {
            Text(lang.s("control.ir.learnAlertHint"))
        }
    }

    // زر تحكّم موحّد صغير (ثانوي).
    @ViewBuilder
    private func controlButton(_ title: String, _ icon: String,
                               action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: Theme.Spacing.xs) {
                Image(systemName: icon)
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                Text(title)
                    .font(Theme.Typography.caption)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
            .foregroundColor(Theme.Colors.accentDeep)
            .frame(maxWidth: .infinity)
            .padding(.vertical, Theme.Spacing.sm)
            .background {
                let shape = RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                ZStack {
                    shape.fill(.ultraThinMaterial)
                    shape.fill(Theme.Colors.accent.opacity(0.08))
                }
            }
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                    .stroke(Theme.Colors.accent.opacity(0.35), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .disabled(store.demo)
    }

    private func iconForType(_ type: String) -> String {
        switch type {
        case "switch": return "power"
        case "dimmer": return "lightbulb.fill"
        case "cover":  return "blinds.horizontal.closed"
        case "media":  return "music.note"
        case "enum":   return "slider.horizontal.3"
        case "ir":     return "dot.radiowaves.left.and.right"
        default:        return "switch.2"
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// MARK: - بطاقة وحدة ساندي

/// بطاقة وحدة مربوطة: نقطة اتصال + اسم + عدد المخارج + الإصدار. القائمة السياقية
/// تعيد التسمية أو تفكّ الربط.
private struct NodeCard: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    let node: NodeItem
    @ObservedObject var store: DevicesStore
    let onRename: () -> Void

    var body: some View {
        HStack(spacing: Theme.Spacing.md) {
            ZStack {
                Circle()
                    .fill(Theme.Colors.secondary.opacity(0.14))
                    .frame(width: 44, height: 44)
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(Theme.Colors.secondary)
            }
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(node.label)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                HStack(spacing: Theme.Spacing.sm) {
                    Circle()
                        .fill(node.online ? Theme.Colors.success : Theme.Colors.tertiaryText)
                        .frame(width: 7, height: 7)
                    Text(node.online ? lang.s("control.online") : lang.s("control.offline"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(node.online ? Theme.Colors.success : Theme.Colors.tertiaryText)
                    Text("•")
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.tertiaryText)
                    Text(String(format: lang.s("control.node.outputs"), "\(node.outputs.count)"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.tertiaryText)
                }
            }
            Spacer(minLength: 0)
        }
        .sandyCard()
        .contextMenu {
            if !store.demo {
                Button { onRename() } label: {
                    Label(lang.s("control.node.rename"), systemImage: "pencil")
                }
                Button(role: .destructive) {
                    store.unpair(api: state.api, node: node)
                } label: { Label(lang.s("control.node.unpair"), systemImage: "minus.circle") }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// MARK: - الستور (مصدر الحقيقة للأجهزة + الوحدات)

/// يملك الأجهزة + الوحدات والجلب والتحكّم والتعديلات، مستقل عن دورة حياة الشاشة.
/// الجلب بمهمة مملوكة للستور فإلغاء السحب ما يلغيه، والتحكّم متفائل ثم مصالحة.
@MainActor
final class DevicesStore: ObservableObject {
    @Published var devices: [DeviceItem] = []
    @Published var nodes: [NodeItem] = []
    @Published var loading = false
    @Published var demo = false
    @Published var notice = ""

    private var loadTask: Task<Void, Never>?

    /// تجميع الأجهزة حسب الغرفة (الفاضية تتجمّع تحت "بدون غرفة")، مرتّبة بالاسم.
    struct RoomGroup { let room: String; let devices: [DeviceItem] }
    var roomGroups: [RoomGroup] {
        let grouped = Dictionary(grouping: devices) { $0.room }
        return grouped
            .map { RoomGroup(room: $0.key, devices: $0.value) }
            .sorted { a, b in
                // الغرف المسمّاة أولًا (أبجديًا)، و"بدون غرفة" آخرًا.
                if a.room.isEmpty != b.room.isEmpty { return !a.room.isEmpty }
                return a.room < b.room
            }
    }

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                // نجلب الأجهزة والوحدات بالتوازي.
                async let devRes = api.getDevices()
                async let nodeRes = api.getNodes()
                let dev = try await devRes
                let nod = try await nodeRes
                devices = dev.items
                nodes = nod.items
                demo = dev.demo || nod.demo
            } catch {
                if !error.isCancellation {
                    notice = LanguageManager.shared.s("control.loadFailed")
                }
            }
        }
        loadTask = task
        await task.value
    }

    // ── التحكّم (متفائل: نعكس الحالة فورًا ثم نصالح بإعادة الجلب) ──
    func control(api: APIClient, device: DeviceItem, action: String, value: String? = nil) {
        guard !demo else { return }
        // تحديث متفائل للحالة المعروضة.
        if let idx = devices.firstIndex(where: { $0.id == device.id }) {
            switch action {
            case "on", "off":     devices[idx].state = action
            case "set":           devices[idx].state = value ?? devices[idx].state
            case "open":          devices[idx].state = "open"
            case "close":         devices[idx].state = "close"
            default:              break
            }
        }
        Task { @MainActor in
            do {
                try await api.controlDevice(name: device.name, action: action, value: value)
                await load(api: api)   // مصالحة مع الحالة الحقيقية من الباك-إند
            } catch {
                if !error.isCancellation {
                    notice = LanguageManager.shared.s("control.controlFailed")
                }
                await load(api: api)
            }
        }
    }

    // ── إضافة/تعديل/حذف جهاز ──
    func add(api: APIClient, draft: DeviceDraft) async throws {
        try await api.addDevice(name: draft.name, label: draft.label,
                                controlType: draft.controlType, transport: draft.transport,
                                room: draft.room, meta: draft.meta)
        await load(api: api)
    }

    func update(api: APIClient, device: DeviceItem, draft: DeviceDraft) async throws {
        try await api.updateDevice(name: device.name, label: draft.label, room: draft.room,
                                   controlType: draft.controlType, transport: draft.transport,
                                   meta: draft.meta)
        await load(api: api)
    }

    func delete(api: APIClient, device: DeviceItem) {
        devices.removeAll { $0.id == device.id }
        Task { @MainActor in
            do {
                try await api.deleteDevice(name: device.name)
            } catch {
                notice = LanguageManager.shared.s("control.deleteFailed")
                await load(api: api)
            }
        }
    }

    // ── الوحدات: ربط/تسمية/فكّ ──
    func pair(api: APIClient, code: String, label: String?) async throws {
        let res = try await api.pairNode(code: code, label: label)
        if res.already { notice = LanguageManager.shared.s("control.node.already") }
        await load(api: api)
    }

    func rename(api: APIClient, node: NodeItem, label: String) async throws {
        try await api.renameNode(nodeId: node.nodeId, label: label)
        await load(api: api)
    }

    func unpair(api: APIClient, node: NodeItem) {
        nodes.removeAll { $0.id == node.id }
        Task { @MainActor in
            do {
                try await api.unpairNode(nodeId: node.nodeId)
            } catch {
                notice = LanguageManager.shared.s("control.deleteFailed")
            }
            await load(api: api)
        }
    }

    // ── تعلّم زر ريموت فعليًّا: ضع الوحدة بوضع التعلّم، استفتِ آخر كود التُقط،
    //    ثم اربطه بالزر. يشتغل فقط لجهاز أشعة مربوط بوحدة. ──
    @Published var learning = false

    func learnIR(api: APIClient, device: DeviceItem, button: String) {
        let name = button.trimmingCharacters(in: .whitespaces)
        let nodeId = device.transport.nodeId
        guard !name.isEmpty else { return }
        guard !nodeId.isEmpty else {
            notice = LanguageManager.shared.s("control.ir.needNode")
            return
        }
        guard !learning else { return }
        learning = true
        Task { @MainActor in
            defer { learning = false }
            do {
                let baseline = try? await api.nodeIrLast(nodeId: nodeId)
                try await api.nodeIrLearnStart(nodeId: nodeId)
                // استفتِ حتى عشر ثوانٍ عن كود جديد (الـ at تغيّر + كود غير فاضي).
                for _ in 0..<10 {
                    try? await Task.sleep(nanoseconds: 1_000_000_000)
                    let last = try await api.nodeIrLast(nodeId: nodeId)
                    if !last.code.isEmpty && last.at != (baseline?.at ?? "") {
                        try await api.irLearn(name: device.name, button: name, code: last.code)
                        await load(api: api)
                        return
                    }
                }
                notice = LanguageManager.shared.s("control.ir.learnTimeout")
            } catch {
                notice = LanguageManager.shared.s("control.ir.learnFailed")
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// MARK: - مسوّدة جهاز (حمولة الإضافة/التعديل من الشيت للستور)

/// قيم الجهاز الجاهزة للإرسال — الشيت يبنيها ويسلّمها للستور.
struct DeviceDraft {
    let name: String           // معرّف ثابت (يُولَّد من التسمية عند الإضافة)
    let label: String
    let room: String
    let controlType: String
    let transport: DeviceTransport
    let meta: [String: Any]
}

// ─────────────────────────────────────────────────────────────────────────
// MARK: - شيت إضافة/تعديل جهاز

/// أنواع التحكّم المدعومة — يطابق قيم control_type بالباك-إند. للعرض نترجم
/// التسمية عبر مفتاح l10n، لكن القيمة المُرسلة (rawValue) تبقى قانونية ثابتة.
private enum ControlType: String, CaseIterable, Identifiable {
    case `switch`, dimmer, `enum`, media, cover, ir
    var id: String { rawValue }
    var labelKey: String { "control.type.\(rawValue)" }
}

/// طريقة الوصل بالواجهة — وحدة ساندي (مخرج) أو إم كيو تي تي خام.
private enum TransportKind: String, CaseIterable, Identifiable {
    case node, mqtt
    var id: String { rawValue }
    var labelKey: String { rawValue == "node" ? "control.transport.node" : "control.transport.mqtt" }
}

/// شيت جهاز (إضافة أو تعديل): اسم + غرفة + نوع تحكّم + طريقة وصل (وحدة/مخرج أو
/// موضوع MQTT خام) + ميتا حسب النوع (خيارات enum، حدّا dimmer) + صف تعليم زر
/// للريموت. `existing` غير nil ⇒ وضع تعديل. الأخطاء بصوت ساندي.
private struct DeviceSheet: View {
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
        let base = trimmedLabel.lowercased()
            .replacingOccurrences(of: " ", with: "-")
        let cleaned = base.filter { $0.isLetter || $0.isNumber || $0 == "-" }
        let slug = cleaned.isEmpty ? "device" : cleaned
        // لاحقة قصيرة تتفادى التصادم.
        return "\(slug)-\(Int(Date().timeIntervalSince1970) % 100000)"
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

// ─────────────────────────────────────────────────────────────────────────
// MARK: - شيت ربط وحدة ساندي

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

// ─────────────────────────────────────────────────────────────────────────
// MARK: - شيت إعادة تسمية وحدة

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
