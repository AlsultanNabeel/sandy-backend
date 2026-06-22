import SwiftUI

/// تبويب الفوكس — مؤقّت بومودورو مربوط بمشاهد الغرفة + محرّر مشاهد (تحكّم
/// room-node عبر MQTT) + إحصائيات. يطابق studio.focus.* بالويب.
struct FocusView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    enum Sub: String, CaseIterable { case timer, scenes, stats }
    @State private var sub: Sub = .timer

    /// المشاهد مشتركة: المؤقّت يحتاجها لاختيار مشهد البداية/النهاية، وقسم
    /// المشاهد يحرّرها.
    @State private var scenes: [RoomScene] = []
    @State private var demo = false

    var body: some View {
        ZStack {
            SandyBackground()
            VStack(spacing: 0) {
                if demo { DemoBanner() }
                subPicker
                ScrollView {
                    VStack(spacing: Theme.Spacing.md) {
                        switch sub {
                        case .timer:  TimerSection(scenes: scenes)
                        case .scenes: ScenesSection(scenes: $scenes, demo: demo) { await loadScenes() }
                        case .stats:  StatsSection()
                        }
                    }
                    .padding(Theme.Spacing.md)
                    .padding(.bottom, Theme.Spacing.xxl + Theme.Spacing.xl)
                }
                .refreshable { await loadScenes() }
            }
        }
        .navigationTitle(lang.s("tabs.focus"))
        .task { await loadScenes() }
    }

    private var subPicker: some View {
        Picker("", selection: $sub) {
            Text(lang.s("focus.sub.timer")).tag(Sub.timer)
            Text(lang.s("focus.sub.scenes")).tag(Sub.scenes)
            Text(lang.s("focus.sub.stats")).tag(Sub.stats)
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, Theme.Spacing.sm)
    }

    private func loadScenes() async {
        do {
            let r = try await state.api.getScenes()
            scenes = r.items
            demo = r.demo
        } catch { /* صامت — الأقسام تتحمّل الغياب */ }
    }
}

// MARK: - المؤقّت (بومودورو)

private struct TimerSection: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    let scenes: [RoomScene]

    @State private var status = FocusStatus()
    @State private var loaded = false
    @State private var notice = ""

    // إعدادات جلسة جديدة
    @State private var label = ""
    @State private var focusMin = "25"
    @State private var breakMin = "5"
    @State private var cycles = "4"
    @State private var startScene = ""
    @State private var endScene = ""
    @State private var busy = false

    private let tick = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(spacing: Theme.Spacing.md) {
            if !notice.isEmpty {
                SandyNotice(notice, kind: .gentleWarning)
            }
            if status.active {
                runningCard
            } else {
                setupCard
            }
        }
        .onReceive(tick) { _ in
            guard status.active else { return }
            if status.remainingSec > 0 { status.remainingSec -= 1 }
            else { Task { await refresh() } }   // انتهى الطور — زامن مع السيرفر
        }
        .task {
            await refresh()
            loaded = true
        }
    }

    // ── جلسة شغّالة: حلقة عدّ تنازلي + الطور + الدورة + أزرار الإنهاء ──────
    private var runningCard: some View {
        SandyCard {
            VStack(spacing: Theme.Spacing.md) {
                ZStack {
                    Circle()
                        .stroke(Theme.Colors.border, lineWidth: 10)
                    Circle()
                        .trim(from: 0, to: progress)
                        .stroke(
                            LinearGradient(colors: [Theme.Colors.accent, Theme.Colors.accentDeep],
                                           startPoint: .top, endPoint: .bottom),
                            style: StrokeStyle(lineWidth: 10, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                        .animation(.linear(duration: 0.5), value: progress)
                    VStack(spacing: 2) {
                        Text(clock(status.remainingSec))
                            .font(.system(size: 40, weight: .bold, design: .rounded))
                            .foregroundColor(Theme.Colors.primaryText)
                            .monospacedDigit()
                        Text(status.isBreak ? lang.s("focus.timer.phaseBreak")
                                             : lang.s("focus.timer.phaseFocus"))
                            .font(Theme.Typography.callout)
                            .foregroundColor(status.isBreak ? Theme.Colors.warn : Theme.Colors.accent)
                    }
                }
                .frame(width: 200, height: 200)

                if !status.label.isEmpty {
                    Text(status.label)
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                }
                Text("\(lang.s("focus.timer.cycle")) \(status.cycleIdx)/\(status.cycles)")
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)

                HStack(spacing: Theme.Spacing.md) {
                    SandyButton(title: lang.s("focus.timer.finish"),
                                systemImage: "checkmark", isLoading: busy) {
                        Task { await stop(cancel: false) }
                    }
                    SandyButton(title: lang.s("focus.timer.cancel"),
                                systemImage: "xmark", style: .secondary) {
                        Task { await stop(cancel: true) }
                    }
                }
            }
            .frame(maxWidth: .infinity)
        }
    }

    // ── إعداد جلسة جديدة ─────────────────────────────────────────────────
    private var setupCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                TextField(lang.s("focus.timer.labelPlaceholder"), text: $label)
                    .textFieldStyle(.plain)
                    .padding(Theme.Spacing.sm)
                    .background(RoundedRectangle(cornerRadius: Theme.Radius.control)
                        .fill(.ultraThinMaterial))

                HStack(spacing: Theme.Spacing.sm) {
                    numField(lang.s("focus.timer.focusMin"), $focusMin)
                    numField(lang.s("focus.timer.breakMin"), $breakMin)
                    numField(lang.s("focus.timer.cycles"), $cycles)
                }

                sceneMenu(lang.s("focus.timer.scene"), $startScene)
                sceneMenu(lang.s("focus.timer.endScene"), $endScene)

                SandyButton(title: lang.s("focus.timer.start"),
                            systemImage: "play.fill", isLoading: busy, fillWidth: true) {
                    Task { await start() }
                }
            }
        }
    }

    private func numField(_ title: String, _ value: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
            TextField("0", text: value)
                .keyboardType(.numberPad)
                .multilineTextAlignment(.center)
                .padding(Theme.Spacing.sm)
                .background(RoundedRectangle(cornerRadius: Theme.Radius.control)
                    .fill(.ultraThinMaterial))
        }
    }

    private func sceneMenu(_ title: String, _ value: Binding<String>) -> some View {
        HStack {
            Text(title)
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.secondaryText)
            Spacer()
            Picker(title, selection: value) {
                Text(lang.s("focus.timer.noScene")).tag("")
                ForEach(scenes) { sc in
                    Text("\(sc.icon) \(sc.label)").tag(sc.name)
                }
            }
            .pickerStyle(.menu)
            .tint(Theme.Colors.accent)
        }
    }

    private var progress: CGFloat {
        guard status.totalSec > 0 else { return 0 }
        return CGFloat(status.remainingSec) / CGFloat(status.totalSec)
    }

    private func clock(_ sec: Int) -> String {
        String(format: "%02d:%02d", max(0, sec) / 60, max(0, sec) % 60)
    }

    private func refresh() async {
        do { status = try await state.api.getFocusStatus() }
        catch { /* صامت */ }
    }

    private func start() async {
        busy = true; notice = ""
        do {
            try await state.api.startFocus(
                focusMin: Int(focusMin) ?? 25,
                breakMin: Int(breakMin) ?? 0,
                cycles: Int(cycles) ?? 1,
                scene: startScene, endScene: endScene, label: label)
            await refresh()
        } catch {
            notice = lang.s(error.localizedDescription == "already_active"
                            ? "focus.timer.alreadyActive" : "focus.timer.startError")
        }
        busy = false
    }

    private func stop(cancel: Bool) async {
        busy = true
        do {
            try await state.api.stopFocus(cancel: cancel)
            await refresh()
        } catch {
            notice = lang.s("focus.timer.stopError")
        }
        busy = false
    }
}

// MARK: - مشاهد الغرفة (تحكّم room-node)

private struct ScenesSection: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @Binding var scenes: [RoomScene]
    let demo: Bool
    let reload: () async -> Void

    @State private var notice = ""
    @State private var busyName = ""
    @State private var editing: RoomScene?
    @State private var showAdd = false

    var body: some View {
        VStack(spacing: Theme.Spacing.md) {
            if !notice.isEmpty {
                SandyNotice(notice, kind: .info)
            }
            if scenes.isEmpty {
                Text(lang.s("focus.scenes.empty"))
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .padding(.top, Theme.Spacing.lg)
            }
            ForEach(scenes) { scene in
                sceneCard(scene)
            }
            if !demo {
                SandyButton(title: lang.s("focus.scenes.add"),
                            systemImage: "plus.circle.fill", style: .secondary, fillWidth: true) {
                    showAdd = true
                }
            }
        }
        .sheet(item: $editing) { sc in
            SceneEditorSheet(scene: sc) { await reload() }
                .environmentObject(state).environmentObject(lang)
        }
        .sheet(isPresented: $showAdd) {
            SceneEditorSheet(scene: nil) { await reload() }
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
                    Task { await apply(scene) }
                } label: {
                    HStack(spacing: 4) {
                        if busyName == scene.name {
                            ProgressView().tint(Theme.Colors.onAccent)
                        } else {
                            Image(systemName: "play.fill")
                        }
                        Text(lang.s("focus.scenes.apply"))
                    }
                    .font(Theme.Typography.button)
                    .foregroundColor(Theme.Colors.onAccent)
                    .padding(.vertical, 8).padding(.horizontal, Theme.Spacing.md)
                    .background(Capsule().fill(
                        LinearGradient(colors: [Theme.Colors.accent, Theme.Colors.accentDeep],
                                       startPoint: .topLeading, endPoint: .bottomTrailing)))
                }
                .buttonStyle(.plain)
                .disabled(demo)
            }
        }
        .contextMenu {
            if !demo {
                Button { editing = scene } label: {
                    Label(lang.s("focus.scenes.edit"), systemImage: "slider.horizontal.3")
                }
                Button(role: .destructive) { Task { await remove(scene) } } label: {
                    Label(lang.s("focus.scenes.delete"), systemImage: "trash")
                }
            }
        }
    }

    private func actionsSummary(_ actions: [SceneAction]) -> String {
        actions.map { "\(deviceIcon($0.device)) \($0.value)" }.joined(separator: " · ")
    }

    private func apply(_ scene: RoomScene) async {
        busyName = scene.name; notice = ""
        do {
            let r = try await state.api.applyScene(name: scene.name)
            notice = lang.s(r.online ? "focus.scenes.applied" : "focus.scenes.appliedOffline")
        } catch {
            notice = lang.s("focus.scenes.applyError")
        }
        busyName = ""
    }

    private func remove(_ scene: RoomScene) async {
        do {
            try await state.api.deleteScene(name: scene.name)
            await reload()
        } catch {
            notice = lang.s(error.localizedDescription == "builtin"
                            ? "focus.scenes.builtinDel" : "focus.scenes.saveError")
        }
    }
}

// MARK: - محرّر مشهد (إضافة/تعديل الأجهزة)

private struct SceneEditorSheet: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    /// nil = إضافة مشهد جديد، غير nil = تعديل أفعال مشهد قائم.
    let scene: RoomScene?
    let onDone: () async -> Void

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
                            field(lang.s("focus.scenes.labelPlaceholder"), $label)
                            field(lang.s("focus.scenes.namePlaceholder"), $name)
                        }

                        ForEach($actions) { $act in
                            actionRow($act)
                        }

                        SandyButton(title: lang.s("focus.scenes.addAction"),
                                    systemImage: "plus", style: .secondary) {
                            actions.append(SceneAction(device: "light", value: "60"))
                        }

                        SandyButton(title: lang.s("focus.scenes.save"),
                                    systemImage: "checkmark", isLoading: busy, fillWidth: true) {
                            Task { await save() }
                        }
                    }
                    .padding(Theme.Spacing.md)
                }
            }
            .navigationTitle(scene?.label ?? lang.s("focus.scenes.add"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("focus.timer.cancel")) { dismiss() }
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
        let clean = actions.filter { !$0.device.isEmpty && !$0.value.trimmingCharacters(in: .whitespaces).isEmpty }
        do {
            if let scene {
                try await state.api.setSceneActions(name: scene.name, actions: clean)
            } else {
                let slug = name.trimmingCharacters(in: .whitespaces)
                    .lowercased().replacingOccurrences(of: " ", with: "_")
                guard !slug.isEmpty else { busy = false; return }
                try await state.api.addScene(name: slug,
                                             label: label.isEmpty ? slug : label,
                                             icon: icon, actions: clean)
            }
            await onDone()
            dismiss()
        } catch {
            err = lang.s(error.localizedDescription == "exists"
                         ? "focus.scenes.nameExists" : "focus.scenes.saveError")
        }
        busy = false
    }
}

// MARK: - إحصائيات (تاريخ الجلسات)

private struct StatsSection: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @State private var history: [FocusSession] = []
    @State private var loaded = false

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Text(lang.s("focus.stats.historyTitle"))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)

            if loaded && history.isEmpty {
                Text(lang.s("focus.stats.noHistory"))
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.secondaryText)
            }
            ForEach(history) { h in
                SandyCard {
                    HStack(spacing: Theme.Spacing.md) {
                        Image(systemName: h.completed ? "checkmark.circle.fill" : "stop.circle")
                            .foregroundColor(h.completed ? Theme.Colors.success : Theme.Colors.secondaryText)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(h.label.isEmpty ? lang.s("focus.timer.phaseFocus") : h.label)
                                .font(Theme.Typography.body)
                                .foregroundColor(Theme.Colors.primaryText)
                            if !h.completed {
                                Text(lang.s("focus.stats.cancelled"))
                                    .font(Theme.Typography.caption)
                                    .foregroundColor(Theme.Colors.secondaryText)
                            }
                        }
                        Spacer(minLength: 0)
                        Text("\(h.minutes) \(lang.s("focus.stats.min"))")
                            .font(Theme.Typography.headline)
                            .foregroundColor(Theme.Colors.accent)
                            .monospacedDigit()
                    }
                }
            }
        }
        .task {
            history = (try? await state.api.getFocusHistory()) ?? []
            loaded = true
        }
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
