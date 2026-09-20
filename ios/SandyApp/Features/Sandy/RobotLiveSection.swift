import SwiftUI

/// رأس شاشة الروبوت: ساندي كما هي **الآن** — متّصلة ولا لأ، آخر ظهور، وشها
/// بمزاجها الحالي، قوّة الواي فاي، نسخة الفيرموير، وأزرار سريعة (مزاج، حركة،
/// نغمة، إضاءة) عبر نقاط التحكّم القائمة. النبض يملكه `RobotStore`.
struct RobotLiveSection: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var store: RobotStore

    private let moodColumns = [GridItem(.adaptive(minimum: 64), spacing: Theme.Spacing.sm)]

    var body: some View {
        VStack(spacing: Theme.Spacing.md) {
            if let node = store.live {
                hero(node)
                stats(node)
                if store.has(SandyMood.Device.face) { moodGrid }
                if store.has(SandyMood.Device.gesture) {
                    chips("live.gestures", icon: "figure.wave", device: SandyMood.Device.gesture,
                          values: store.values(SandyMood.Device.gesture, fallback: SandyMood.gestures),
                          prefix: "gesture", selectable: false)
                }
                if store.has(SandyMood.Device.buzzer) {
                    chips("live.melodies", icon: "music.note", device: SandyMood.Device.buzzer,
                          values: store.values(SandyMood.Device.buzzer, fallback: SandyMood.melodies),
                          prefix: "melody", selectable: false)
                }
                if store.has(SandyMood.Device.led) {
                    chips("live.led", icon: "lightbulb.led.fill", device: SandyMood.Device.led,
                          values: store.values(SandyMood.Device.led, fallback: SandyMood.leds),
                          prefix: "led", selectable: true)
                }
            } else if store.liveLoaded && !store.demo {
                SandyCard {
                    HStack(spacing: Theme.Spacing.md) {
                        SandyRobot(size: 40, animated: false, mood: "sleepy")
                        Text(lang.s("robot.live.noRobot"))
                            .font(Theme.Typography.subheadline)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                }
            } else if !store.liveLoaded {
                ProgressView().tint(Theme.Colors.accent)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Spacing.lg)
            }
        }
        .animation(.easeInOut(duration: 0.3), value: store.live)
    }

    // MARK: البطل — الوجه + الحالة

    private func hero(_ node: RobotLiveNode) -> some View {
        VStack(spacing: Theme.Spacing.sm) {
            SandyRobot(size: 110, animated: node.online, mood: store.displayMood)
                .opacity(node.online ? 1 : 0.45)
                .saturation(node.online ? 1 : 0)
                .animation(.spring(response: 0.4, dampingFraction: 0.75), value: store.displayMood)
                .padding(.top, Theme.Spacing.xs)

            Text(node.label)
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)

            HStack(spacing: Theme.Spacing.sm) {
                statusPill(node.online)
                Text(lastSeenText(node))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
            }

            Text(String(format: lang.s("robot.live.currentMood"), label("mood", store.displayMood)))
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.accent)
        }
        .frame(maxWidth: .infinity)
        .sandyCard(.primary)
    }

    private func statusPill(_ online: Bool) -> some View {
        let color = online ? Theme.Colors.success : Theme.Colors.tertiaryText
        return HStack(spacing: Theme.Spacing.xs) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(lang.s(online ? "robot.live.online" : "robot.live.offline"))
                .font(Theme.Typography.caption)
                .foregroundColor(color)
        }
        .padding(.horizontal, Theme.Spacing.sm).padding(.vertical, Theme.Spacing.xs)
        .background(Capsule().fill(color.opacity(0.14)))
    }

    private func lastSeenText(_ node: RobotLiveNode) -> String {
        guard let at = node.lastSeen else { return lang.s("robot.live.neverSeen") }
        return String(format: lang.s("robot.live.lastSeen"), AppLocale.relative(at))
    }

    // MARK: قراءات — الواي فاي والنسخة

    private func stats(_ node: RobotLiveNode) -> some View {
        HStack(spacing: Theme.Spacing.sm) {
            statTile(icon: wifiIcon(node.rssi), title: lang.s("robot.live.wifi"),
                     value: wifiText(node), tint: wifiColor(node.rssi))
            statTile(icon: "cpu", title: lang.s("robot.live.firmware"),
                     value: node.firmwareVersion.isEmpty ? lang.s("robot.live.unknown")
                                                         : node.firmwareVersion,
                     tint: Theme.Colors.accent)
        }
    }

    private func statTile(icon: String, title: String, value: String, tint: Color) -> some View {
        HStack(spacing: Theme.Spacing.sm) {
            Image(systemName: icon)
                .font(.system(size: Theme.Icon.md, weight: .semibold))
                .foregroundColor(tint)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                Text(value)
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.primaryText)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
            Spacer(minLength: 0)
        }
        .sandyCard(.info)
    }

    private func wifiText(_ node: RobotLiveNode) -> String {
        guard node.online, let rssi = node.rssi else { return lang.s("robot.live.unknown") }
        let quality: String
        switch rssi {
        case -55...0:   quality = "robot.live.wifi.excellent"
        case -67 ..< -55: quality = "robot.live.wifi.good"
        case -75 ..< -67: quality = "robot.live.wifi.fair"
        default:        quality = "robot.live.wifi.weak"
        }
        return lang.s(quality) + " · " + AppLocale.number(rssi) + " dBm"
    }

    private func wifiIcon(_ rssi: Int?) -> String {
        guard let rssi else { return "wifi.slash" }
        return rssi >= -75 ? "wifi" : "wifi.exclamationmark"
    }

    private func wifiColor(_ rssi: Int?) -> Color {
        guard let rssi, store.live?.online == true else { return Theme.Colors.tertiaryText }
        if rssi >= -67 { return Theme.Colors.success }
        return rssi >= -75 ? Theme.Colors.warn : Theme.Colors.danger
    }

    // MARK: شبكة المزاج — الخمسة وعشرين

    private var moodGrid: some View {
        let moods = store.values(SandyMood.Device.face, fallback: SandyMood.all)
        let enabled = !store.demo
        return VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            sectionTitle("live.moods", icon: "face.smiling")
            LazyVGrid(columns: moodColumns, spacing: Theme.Spacing.sm) {
                ForEach(moods, id: \.self) { mood in
                    let selected = store.displayMood == mood
                    Button {
                        Task { await store.send(api: state.api, device: SandyMood.Device.face, value: mood) }
                    } label: {
                        VStack(spacing: Theme.Spacing.xs) {
                            SandyRobot(size: 26, animated: false, mood: mood)
                                .frame(height: 42)
                            Text(label("mood", mood))
                                .font(.system(size: 11, weight: .medium, design: .rounded))
                                .foregroundColor(selected ? Theme.Colors.accent : Theme.Colors.secondaryText)
                                .lineLimit(1)
                                .minimumScaleFactor(0.7)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Theme.Spacing.sm)
                        .background(
                            RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                                .fill(selected ? Theme.Colors.accent.opacity(0.14) : Color.white.opacity(0.04)))
                        .overlay(
                            RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                                .stroke(selected ? Theme.Colors.accent.opacity(0.6) : Color.clear, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                    .disabled(!enabled)
                    .accessibilityLabel(label("mood", mood))
                    .accessibilityAddTraits(selected ? .isSelected : [])
                }
            }
        }
        .sandyCard(.secondary)
    }

    // MARK: شرائح — حركة / نغمة / إضاءة

    private func chips(_ titleKey: String, icon: String, device: String, values: [String],
                       prefix: String, selectable: Bool) -> some View {
        let current = store.parts[device]?.state ?? ""
        return VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            sectionTitle(titleKey, icon: icon)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Theme.Spacing.sm) {
                    ForEach(values, id: \.self) { v in
                        let selected = selectable && current == v
                        let busy = store.sending == device + ":" + v
                        Button {
                            Task { await store.send(api: state.api, device: device, value: v) }
                        } label: {
                            HStack(spacing: Theme.Spacing.xs) {
                                if busy {
                                    ProgressView().controlSize(.mini)
                                }
                                Text(label(prefix, v))
                                    .font(Theme.Typography.caption)
                            }
                            .foregroundColor(selected ? Theme.Colors.onAccent : Theme.Colors.primaryText)
                            .padding(.horizontal, Theme.Spacing.md)
                            .padding(.vertical, Theme.Spacing.sm)
                            .background(Capsule().fill(selected ? Theme.Colors.accent
                                                                : Color.white.opacity(0.08)))
                        }
                        .buttonStyle(.plain)
                        .disabled(store.demo || !store.sending.isEmpty)
                    }
                }
                .padding(.vertical, 2)
            }
        }
        .sandyCard(.secondary)
    }

    private func sectionTitle(_ key: String, icon: String) -> some View {
        Label(lang.s("robot." + key), systemImage: icon)
            .font(Theme.Typography.headline)
            .foregroundColor(Theme.Colors.primaryText)
    }

    /// تسمية ثنائية اللغة لقيمة؛ قيمة جديدة من فيرموير أحدث بتبيّن باسمها الخام.
    private func label(_ prefix: String, _ value: String) -> String {
        let key = "robot." + prefix + "." + value
        let s = lang.s(key)
        return s == key ? value.replacingOccurrences(of: "_", with: " ") : s
    }
}
