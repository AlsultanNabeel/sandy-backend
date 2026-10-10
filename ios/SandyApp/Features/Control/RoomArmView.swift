import SwiftUI

/// ضبط ذراع ضو الغرفة: الراحة وكبستي التشغيل والإطفاء ومدة الكبسة. «جرّب» بيحرّك الذراع
/// أو بيعمل كبسة كاملة بالقيم اللي على الشاشة بدون حفظ، وما بيغيّر حالة الضو؛ «احفظ» بيخلّي
/// كل كبسة بعدها بهالقيم (`POST /api/nodes/<id>/room/light-arm`).
struct RoomArmView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    let node: NodeItem
    @State private var arm: RoomArm
    @State private var busy = false
    @State private var notice = ""
    @State private var noticeIsGood = false

    init(node: NodeItem) {
        self.node = node
        _arm = State(initialValue: node.telemetry?.roomArm ?? .standard)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                Text(lang.s("control.arm.hint"))
                    .font(Theme.Typography.callout)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)

                angleRow("control.arm.rest", value: $arm.rest)
                angleRow("control.arm.on", value: $arm.on)
                angleRow("control.arm.off", value: $arm.off)

                SandyCard {
                    VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                        HStack {
                            Text(lang.s("control.arm.hold"))
                                .font(Theme.Typography.callout)
                            Spacer(minLength: 0)
                            Text(String(format: lang.s("control.arm.ms"), AppLocale.number(arm.holdMs)))
                                .font(Theme.Typography.headline)
                                .monospacedDigit()
                        }
                        Slider(value: intBinding($arm.holdMs),
                               in: Double(RoomArm.hold.lowerBound)...Double(RoomArm.hold.upperBound),
                               step: 50)
                    }
                }

                if !arm.restBetween {
                    SandyNotice(lang.s("control.arm.restBetween"), kind: .gentleWarning)
                }

                HStack(spacing: Theme.Spacing.sm) {
                    SandyButton(title: lang.s("control.arm.tryOn"), style: .secondary, fillWidth: true) {
                        send("try_on", arm: arm)
                    }
                    SandyButton(title: lang.s("control.arm.tryOff"), style: .secondary, fillWidth: true) {
                        send("try_off", arm: arm)
                    }
                }
                .disabled(busy || !arm.restBetween)
                .opacity(arm.restBetween ? 1 : 0.6)

                SandyButton(title: lang.s("control.arm.save"), systemImage: "checkmark.circle.fill",
                            isLoading: busy, fillWidth: true) {
                    send("save", arm: arm)
                }
                .disabled(busy || !arm.restBetween || arm == node.telemetry?.roomArm)
                .opacity(arm.restBetween ? 1 : 0.6)

                if !notice.isEmpty {
                    SandyNotice(notice, kind: noticeIsGood ? .info : .gentleWarning)
                }
            }
            .padding(Theme.Spacing.lg)
        }
        .background(Theme.Colors.background.ignoresSafeArea())
        .navigationTitle(lang.s("control.arm.title"))
        .environment(\.layoutDirection, lang.lang.layoutDirection)
        .animation(Animation.easeInOut(duration: 0.2).reduced, value: notice)
    }

    private func angleRow(_ key: String, value: Binding<Int>) -> some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                HStack {
                    Text(lang.s(key))
                        .font(Theme.Typography.callout)
                    Spacer(minLength: 0)
                    Text(String(format: lang.s("control.arm.degrees"), AppLocale.number(value.wrappedValue)))
                        .font(Theme.Typography.headline)
                        .monospacedDigit()
                }
                HStack(spacing: Theme.Spacing.sm) {
                    Slider(value: intBinding(value),
                           in: Double(RoomArm.angles.lowerBound)...Double(RoomArm.angles.upperBound),
                           step: 1)
                    Button(lang.s("control.arm.goto")) {
                        send("goto", angle: value.wrappedValue)
                    }
                    .buttonStyle(.bordered)
                    .disabled(busy)
                }
            }
        }
    }

    private func intBinding(_ v: Binding<Int>) -> Binding<Double> {
        Binding(get: { Double(v.wrappedValue) }, set: { v.wrappedValue = Int($0.rounded()) })
    }

    private func send(_ action: String, angle: Int? = nil, arm: RoomArm? = nil) {
        busy = true
        notice = ""
        Task {
            defer { busy = false }
            do {
                try await state.api.roomLightArm(nodeId: node.nodeId, action: action,
                                                 angle: angle, arm: arm)
                if action == "save" {
                    noticeIsGood = true
                    notice = lang.s("control.arm.saved")
                }
            } catch let e as APIError {
                noticeIsGood = false
                notice = lang.s(e.code == "room_offline" ? "control.arm.offline" : "control.arm.failed")
            } catch {
                noticeIsGood = false
                notice = lang.s("control.arm.failed")
            }
        }
    }
}
