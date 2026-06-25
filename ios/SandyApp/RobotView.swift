import SwiftUI

/// تبويب الروبوت — تحكّم بأجهزة الغرفة (room-node عبر MQTT): قائمة المشاهد،
/// تشغيلها، وإضافة/تعديل/حذف. مصدر الحقيقة الوحيد للمشاهد؛ الفوكس يقرأ من نفس
/// الستور قائمة مشاهد البداية/النهاية للمؤقّت. owner-gated بالباك-إند.
struct RobotView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    /// مصدر الحقيقة للمشاهد: يملك البيانات + الجلب + الإجراءات، مستقل عن دورة
    /// حياة الشاشة — فالسحب/التنقّل ما يلغي الجلب.
    @StateObject private var store = RobotStore()

    @State private var editing: RoomScene?
    @State private var showAdd = false

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if store.demo { DemoBanner() }

                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .info)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                content
            }
        }
        .navigationTitle(lang.s("tabs.robot"))
        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.scenes.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .sheet(item: $editing) { sc in
            SceneEditorSheet(store: store, scene: sc)
                .environmentObject(state).environmentObject(lang)
        }
        .sheet(isPresented: $showAdd) {
            SceneEditorSheet(store: store, scene: nil)
                .environmentObject(state).environmentObject(lang)
        }
    }

    private var content: some View {
        ScrollView {
            VStack(spacing: Theme.Spacing.md) {
                if store.scenes.isEmpty && !store.loading {
                    Text(lang.s("robot.empty"))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .padding(.top, Theme.Spacing.xl)
                }

                ForEach(store.scenes) { scene in
                    sceneCard(scene)
                }

                if !store.demo {
                    SandyButton(title: lang.s("robot.add"),
                                systemImage: "plus.circle.fill", style: .secondary, fillWidth: true) {
                        showAdd = true
                    }
                }
            }
            .padding(Theme.Spacing.md)
            .padding(.bottom, Theme.Spacing.xxl + Theme.Spacing.xl)
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
                    HStack(spacing: 4) {
                        if store.applying == scene.name {
                            ProgressView().tint(Theme.Colors.onAccent)
                        } else {
                            Image(systemName: "play.fill")
                        }
                        Text(lang.s("robot.apply"))
                    }
                    .font(Theme.Typography.button)
                    .foregroundColor(Theme.Colors.onAccent)
                    .padding(.vertical, 8).padding(.horizontal, Theme.Spacing.md)
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

// MARK: - الستور (مصدر الحقيقة للمشاهد)

/// نمط الستور المعتمد: `ObservableObject` على `@MainActor`، والجلب يجري في مهمة
/// يملكها الستور — فإلغاء إيماءة الواجهة (سحب/تنقّل) ما يلغي الجلب.
@MainActor
final class RobotStore: ObservableObject {
    @Published var scenes: [RoomScene] = []
    @Published var loading = false
    @Published var demo = false
    /// رسالة ودّية بصوت ساندي (فاضية = ما في خطأ/إشعار).
    @Published var notice = ""
    /// اسم المشهد الجاري تطبيقه (لمؤشّر الزر داخل بطاقته).
    @Published var applying = ""

    private var loadTask: Task<Void, Never>?

    /// جلب مملوك للستور وينتظره — يصلح للـ `.task` و`.refreshable` معاً.
    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                let r = try await api.getScenes()
                scenes = r.items
                demo = r.demo
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("robot.loadError") }
            }
        }
        loadTask = task
        await task.value
    }

    /// يطبّق مشهداً وينشر نتيجته (متّصل/غير متّصل/خطأ) كإشعار ودّي.
    func apply(api: APIClient, scene: RoomScene) async {
        applying = scene.name; notice = ""
        do {
            let r = try await api.applyScene(name: scene.name)
            notice = LanguageManager.shared.s(r.online ? "robot.applied" : "robot.appliedOffline")
        } catch {
            notice = LanguageManager.shared.s("robot.applyError")
        }
        applying = ""
    }

    /// إضافة مشهد جديد ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, name: String, label: String, icon: String,
             actions: [SceneAction]) async -> Bool {
        do {
            try await api.addScene(name: name, label: label, icon: icon, actions: actions)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s(error.localizedDescription == "exists"
                                              ? "robot.nameExists" : "robot.saveError")
            return false
        }
    }

    /// تعديل أفعال مشهد قائم ثم إعادة جلب. يرجّع نجاح/فشل.
    func update(api: APIClient, scene: RoomScene, actions: [SceneAction]) async -> Bool {
        do {
            try await api.setSceneActions(name: scene.name, actions: actions)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("robot.saveError")
            return false
        }
    }

    /// حذف مشهد ثم إعادة جلب.
    func remove(api: APIClient, scene: RoomScene) async {
        do {
            try await api.deleteScene(name: scene.name)
            await load(api: api)
        } catch {
            notice = LanguageManager.shared.s(error.localizedDescription == "builtin"
                                              ? "robot.builtinDel" : "robot.saveError")
        }
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
