import SwiftUI

/// تبويب الفوكس — مؤقّت بومودورو + إحصائيات. المؤقّت بيربط جلسته بمشهد بداية/نهاية
/// من مشاهد الغرفة، فبيقرأ القائمة من نفس `RobotStore` (للقراءة فقط)؛ إدارة المشاهد
/// نفسها صارت بتبويب الروبوت. يطابق studio.focus.* بالويب.
struct FocusView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    enum Sub: String, CaseIterable { case timer, stats }
    @State private var sub: Sub = .timer

    /// قائمة المشاهد لقوائم البداية/النهاية بالمؤقّت — قراءة فقط من نفس ستور الروبوت.
    @StateObject private var robot = RobotStore()

    var body: some View {
        // الخلفية موحّدة على مستوى MainTabView — لا نكرّرها هون (طبقة مهدورة).
        ZStack {
            VStack(spacing: 0) {
                subPicker
                ScrollView {
                    VStack(spacing: Theme.Spacing.md) {
                        switch sub {
                        case .timer:  TimerSection(scenes: robot.scenes)
                        case .stats:  StatsSection()
                        }
                    }
                    .padding(Theme.Spacing.md)
                    .padding(.bottom, Theme.Spacing.xxl + Theme.Spacing.xl)
                }
                .refreshable { await robot.load(api: state.api) }
            }
        }
        .navigationTitle(lang.s("tabs.focus"))
        .task { await robot.load(api: state.api) }
    }

    private var subPicker: some View {
        Picker("", selection: $sub) {
            Text(lang.s("focus.sub.timer")).tag(Sub.timer)
            Text(lang.s("focus.sub.stats")).tag(Sub.stats)
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, Theme.Spacing.sm)
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
                    VStack(spacing: Theme.Spacing.xs) {
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
        .sandyCard(.primary)
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
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
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
                        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
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
