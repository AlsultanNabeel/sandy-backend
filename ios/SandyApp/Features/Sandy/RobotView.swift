import SwiftUI

/// روبوت ساندي — كل إشي بيخصّها بمكان واحد: حالتها هلأ (متّصلة، وشها، الواي فاي)،
/// جسمها (الوش والشاشة والإضاءة والصوت والكاميرا)، فحص القطع، شبكة اللوح، ليش قطعة
/// مش ظاهرة، وربطها أو فكّها. مشاهد الغرفة مش هون: إلها التحكّم بالبيت.
struct RobotView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    /// Her state now (the live pulse) and her quick buttons.
    @StateObject private var store = RobotStore()
    /// Her parts are devices: the body screen, the parts test and the board's Wi-Fi read them.
    @StateObject private var devices = DevicesStore()

    @Environment(\.scenePhase) private var scenePhase
    /// الشاشة ظاهرة فعلًا — رجوع التطبيق للواجهة ما بيشغّل النبض لتبويب مخفي.
    @State private var visible = false

    /// The board that speaks: the robot (a room node has no audio).
    private var robotNode: NodeItem? {
        devices.nodes.first { $0.capabilities.contains("audio") }
    }

    var body: some View {
        ZStack {
            SandyBackground()
            ScrollView {
                VStack(spacing: Theme.Spacing.md) {
                    if store.demo { DemoBanner() }
                    if !store.notice.isEmpty {
                        SandyNotice(store.notice, kind: .info)
                            .transition(.move(edge: .top).combined(with: .opacity))
                    }
                    RobotLiveSection(store: store)
                    links
                }
                .padding(Theme.Spacing.md)
                .padding(.bottom, Theme.Spacing.xxl + Theme.Spacing.xl)
            }
        }
        .navigationTitle(lang.s("tabs.robot"))
        .animation(Animation.easeInOut(duration: 0.25).reduced, value: store.notice)
        .task { await devices.load(api: state.api) }
        .refreshable {
            await store.refreshLive(api: state.api)
            await devices.load(api: state.api)
        }
        // نبض حي كل خمس ثواني وهي الشاشة ظاهرة بس — بيوقف لما تختفي أو يروح
        // التطبيق للخلفية، وبيرجع لما يرجع.
        .onAppear { visible = true; store.startLive(api: state.api) }
        .onDisappear { visible = false; store.stopLive() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active && visible { store.startLive(api: state.api) } else { store.stopLive() }
        }
    }

    /// Everything else about her, one row each.
    private var links: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                row("figure.wave", "robot.hub.body", "robot.hub.bodyNote") {
                    RobotControlView(store: devices)
                }
                if let node = robotNode {
                    row("waveform.badge.magnifyingglass", "robot.hub.test", "robot.hub.testNote") {
                        RobotTestView(store: devices, node: node)
                    }
                    row("wifi", "wifi.title", "robot.hub.wifiNote") {
                        NodeWiFiView(node: node, onFinished: { await devices.load(api: state.api) })
                    }
                }
                row("stethoscope", "robot.hub.diagnose", "robot.hub.diagnoseNote") { DiagnoseView() }
                row("link", "robot.hub.pairing", "robot.hub.pairingNote") { AccountView() }
            }
        }
    }

    private func row<Destination: View>(_ icon: String, _ titleKey: String, _ noteKey: String,
                                        @ViewBuilder destination: @escaping () -> Destination) -> some View {
        NavigationLink(destination: destination) {
            HStack(spacing: Theme.Spacing.md) {
                Image(systemName: icon)
                    .scaledFont(Theme.Icon.md, weight: .semibold)
                    .foregroundColor(Theme.Colors.accent)
                    .frame(width: 28)
                VStack(alignment: .leading, spacing: 2) {
                    Text(lang.s(titleKey))
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Text(lang.s(noteKey))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.forward")
                    .scaledFont(Theme.Icon.sm, weight: .semibold)
                    .foregroundColor(Theme.Colors.tertiaryText)
            }
            .padding(.vertical, Theme.Spacing.xs)
            .accessibilityElement(children: .combine)
        }
        .buttonStyle(.plain)
    }
}

/// مشاهد الغرفة — بالتحكّم بالبيت: تشغيلها، وإضافتها، وتعديلها، وحذفها. نفس `RobotStore`
/// اللي بيقرأ منه الفوكس مشاهد البداية والنهاية.
struct RoomScenesSection: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var store: RobotStore
    @State private var editing: RoomScene?
    @State private var showAdd = false

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            if store.scenes.isEmpty && !store.loading {
                Text(lang.s("robot.empty"))
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.secondaryText)
            }
            ForEach(store.scenes) { scene in sceneCard(scene) }
            if !store.demo {
                SandyButton(title: lang.s("robot.add"),
                            systemImage: "plus.circle.fill", style: .secondary, fillWidth: true) {
                    showAdd = true
                }
            }
        }
        .animation(Animation.spring(response: 0.45, dampingFraction: 0.8).reduced, value: store.scenes.map(\.id))
        .task { await store.load(api: state.api) }
        .sheet(item: $editing) { sc in
            SceneEditorSheet(store: store, scene: sc)
                .environmentObject(state).environmentObject(lang)
        }
        .sheet(isPresented: $showAdd) {
            SceneEditorSheet(store: store, scene: nil)
                .environmentObject(state).environmentObject(lang)
        }
    }

    private func sceneCard(_ scene: RoomScene) -> some View {
        SandyCard {
            HStack(spacing: Theme.Spacing.md) {
                Text(scene.icon).font(.title2)
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(scene.label)
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Text(actionsSummary(scene.actions))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                Button {
                    Task { await store.apply(api: state.api, scene: scene) }
                } label: {
                    HStack(spacing: Theme.Spacing.xs) {
                        if store.applying == scene.name {
                            LoadingDots(color: Theme.Colors.onAccent)
                        } else {
                            Image(systemName: "play.fill")
                                .scaledFont(Theme.Icon.sm, weight: .semibold)
                        }
                        Text(lang.s("robot.apply"))
                    }
                    .font(Theme.Typography.button)
                    .foregroundColor(Theme.Colors.onAccent)
                    .padding(.vertical, Theme.Spacing.sm).padding(.horizontal, Theme.Spacing.md)
                    .background(Capsule().fill(
                        LinearGradient(colors: [Theme.Colors.accent, Theme.Colors.accentDeep],
                                       startPoint: .topLeading, endPoint: .bottomTrailing)))
                }
                .buttonStyle(.plain)
                .disabled(store.demo)
            }
        }
        .contextMenu {
            if !store.demo {
                Button { editing = scene } label: {
                    Label(lang.s("robot.edit"), systemImage: "slider.horizontal.3")
                }
                Button(role: .destructive) {
                    Task { await store.remove(api: state.api, scene: scene) }
                } label: {
                    Label(lang.s("robot.delete"), systemImage: "trash")
                }
            }
        }
    }

    private func actionsSummary(_ actions: [SceneAction]) -> String {
        actions.map { "\(deviceIcon($0.device)) \($0.value)" }.joined(separator: " · ")
    }
}

// MARK: - محرّر مشهد (إضافة/تعديل الأجهزة)

private struct SceneEditorSheet: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    let store: RobotStore
    /// nil = إضافة مشهد جديد، غير nil = تعديل أفعال مشهد قائم.
    let scene: RoomScene?

    @State private var name = ""
    @State private var label = ""
    @State private var icon = "🎛️"
    @State private var actions: [SceneAction] = []
    @State private var busy = false
    @State private var err = ""

    private var isEditing: Bool { scene != nil }

    var body: some View {
        NavigationStack {
            ZStack {
                SandyBackground()
                ScrollView {
                    VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                        if !err.isEmpty { SandyNotice(err, kind: .gentleWarning) }

                        if !isEditing {
                            field(lang.s("robot.labelPlaceholder"), $label)
                            field(lang.s("robot.namePlaceholder"), $name)
                        }

                        ForEach($actions) { $act in
                            actionRow($act)
                        }

                        SandyButton(title: lang.s("robot.addAction"),
                                    systemImage: "plus", style: .secondary) {
                            actions.append(SceneAction(device: "light", value: "60"))
                        }

                        SandyButton(title: lang.s("robot.save"),
                                    systemImage: "checkmark", isLoading: busy, fillWidth: true) {
                            Task { await save() }
                        }
                    }
                    .padding(Theme.Spacing.md)
                }
            }
            .navigationTitle(scene?.label ?? lang.s("robot.add"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("robot.cancel")) { dismiss() }
                }
            }
        }
        .onAppear {
            if let scene {
                label = scene.label; name = scene.name; icon = scene.icon
                actions = scene.actions
            } else {
                actions = [SceneAction(device: "light", value: "60")]
            }
        }
    }

    private func field(_ placeholder: String, _ value: Binding<String>) -> some View {
        TextField(placeholder, text: value)
            .padding(Theme.Spacing.sm)
            .background(RoundedRectangle(cornerRadius: Theme.Radius.control).fill(.ultraThinMaterial))
    }

    private func actionRow(_ act: Binding<SceneAction>) -> some View {
        HStack(spacing: Theme.Spacing.sm) {
            Picker("", selection: act.device) {
                ForEach(sceneDevices, id: \.self) { d in
                    Text("\(deviceIcon(d)) \(d)").tag(d)
                }
            }
            .pickerStyle(.menu)
            .tint(Theme.Colors.accent)

            // قيمة: قائمة جاهزة لو الجهاز له خيارات، وإلا حقل حر.
            if let opts = deviceOptions[act.wrappedValue.device] {
                Picker("", selection: act.value) {
                    ForEach(opts, id: \.self) { Text($0).tag($0) }
                }
                .pickerStyle(.menu)
                .tint(Theme.Colors.accent)
            } else {
                TextField("0", text: act.value)
                    .keyboardType(.default)
                    .multilineTextAlignment(.center)
                    .padding(Theme.Spacing.sm)
                    .background(RoundedRectangle(cornerRadius: Theme.Radius.control).fill(.ultraThinMaterial))
            }
            Spacer(minLength: 0)
            Button {
                actions.removeAll { $0.id == act.wrappedValue.id }
            } label: {
                Image(systemName: "minus.circle.fill").foregroundColor(Theme.Colors.danger)
                    .accessibilityLabel(LanguageManager.shared.s("a11y.removeAction"))
            }
            .buttonStyle(.plain)
        }
    }

    private func save() async {
        busy = true; err = ""
        let clean = actions.filter {
            !$0.device.isEmpty && !$0.value.trimmingCharacters(in: .whitespaces).isEmpty
        }
        let ok: Bool
        if let scene {
            ok = await store.update(api: state.api, scene: scene, actions: clean)
        } else {
            let slug = name.trimmingCharacters(in: .whitespaces)
                .lowercased().replacingOccurrences(of: " ", with: "_")
            guard !slug.isEmpty else { busy = false; return }
            ok = await store.add(api: state.api, name: slug,
                                 label: label.isEmpty ? slug : label,
                                 icon: icon, actions: clean)
        }
        busy = false
        if ok { dismiss() } else { err = store.notice }
    }
}

// MARK: - أجهزة الغرفة (يطابق SCENE_DEVICES/DEVICE_OPTS بالويب)

private let sceneDevices = ["light", "color", "music", "fan", "curtain", "buzzer"]
private let deviceOptions: [String: [String]] = [
    "color": ["warm", "cool", "white", "red", "green", "blue", "purple", "amber"],
    "music": ["on", "off", "pause"],
    "curtain": ["open", "close"],
    "buzzer": ["boot", "happy", "curious", "sad", "alert", "error",
               "focus_start", "focus_break", "focus_end"],
]
private func deviceIcon(_ d: String) -> String {
    ["light": "💡", "color": "🎨", "music": "🎵",
     "fan": "🌀", "curtain": "🪟", "buzzer": "🔔"][d] ?? "🎛️"
}
