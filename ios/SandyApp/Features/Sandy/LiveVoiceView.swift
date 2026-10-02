import SwiftUI

/// شاشة المكالمة الصوتية الحيّة مع ساندي — جيميني لايف الحقيقي (صوت لصوت لحظي،
/// زي الروبوت/الويب). تحكي وهي تسمع، تردّ بصوتها الفعلي، وفمها يتحرّك على موجة
/// صوتها. بدون كيبورد وبدون نص.
///
/// كل الصوت بـ `GeminiLiveManager`: ويب-سوكت `/voice` ← بثّ المايك ← ردّها اللحظي.
struct LiveVoiceView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @ObservedObject private var live = GeminiLiveManager.shared

    /// نبضة الهالة المستمرة.
    @State private var pulse = false

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: Theme.Spacing.xl) {
                HStack {
                    // Closing the screen keeps the call; the bar over the tabs brings it back.
                    Button { dismiss() } label: {
                        Image(systemName: "chevron.down")
                            .scaledFont(18, weight: .semibold)
                            .foregroundColor(Theme.Colors.secondaryText)
                            .padding(10)
                    }
                    .accessibilityLabel(lang.s("chat.liveMinimize"))
                    Spacer()
                }
                Spacer()
                sandyOrb
                statusLabel
                captions
                Spacer()
                endButton
            }
            .padding(Theme.Spacing.lg)
        }
        .onAppear {
            pulse = true
            if !live.inCall { live.start(baseURL: state.api.baseURL, token: state.api.token ?? "") }
        }
    }

    // MARK: - ساندي + الهالة (تتفاعل مع الطور)

    private var sandyOrb: some View {
        ZStack {
            Circle()
                .fill(
                    RadialGradient(
                        colors: [Theme.Colors.accent.opacity(glow), .clear],
                        center: .center, startRadius: 8, endRadius: 170)
                )
                .frame(width: 320, height: 320)
                .scaleEffect(pulse ? pulseHigh : pulseLow)
                .animation(Animation.easeInOut(duration: pulseSpeed).repeatForever(autoreverses: true).reduced, value: pulse)

            SandyRobot(size: 168,
                       blink: false,
                       happy: true,
                       animated: true,
                       mouthOpen: live.mouthOpen)
                .scaleEffect(live.phase == .speaking ? 1.04 : 1.0)
                .animation(Animation.easeInOut(duration: 0.3).reduced, value: live.phase)
        }
        .frame(height: 320)
    }

    // MARK: - جملة الحالة

    private var statusLabel: some View {
        Text(statusText)
            .font(Theme.Typography.title)
            .foregroundColor(Theme.Colors.primaryText)
            .animation(Animation.easeInOut(duration: 0.2).reduced, value: live.phase)
            .animation(Animation.easeInOut(duration: 0.2).reduced, value: live.working)
    }

    // MARK: - تلميح / خطأ

    @ViewBuilder
    private var captions: some View {
        VStack(spacing: Theme.Spacing.md) {
            if live.permissionDenied {
                PermissionCard(kind: .mic)
                    .task { await Permissions.shared.refresh() }
            } else if !live.errorText.isEmpty {
                Text(live.errorText)
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.warn)
                    .multilineTextAlignment(.center)
            } else if live.phase == .idle || live.phase == .connecting {
                Text(lang.s("chat.liveHint"))
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(minHeight: 80)
        .padding(.horizontal, Theme.Spacing.lg)
        .animation(Animation.easeInOut(duration: 0.25).reduced, value: live.phase)
        .animation(Animation.easeInOut(duration: 0.25).reduced, value: live.errorText)
    }

    // MARK: - زر الإنهاء

    private var endButton: some View {
        Button {
            live.stop()
            dismiss()
        } label: {
            HStack(spacing: Theme.Spacing.sm) {
                Image(systemName: "phone.down.fill")
                Text(lang.s("chat.liveEnd"))
                    .font(Theme.Typography.button)
            }
            .foregroundColor(Theme.Colors.onFill)
            .padding(.vertical, Theme.Spacing.md)
            .padding(.horizontal, Theme.Spacing.xl)
            .background(Theme.Colors.danger)
            .clipShape(Capsule())
            .shadow(color: Theme.Colors.danger.opacity(0.5),
                    radius: 12, x: 0, y: 4)
        }
        .buttonStyle(.plain)
    }

    // MARK: - اشتقاقات الطور

    private var statusText: String {
        switch live.phase {
        case .idle, .connecting: return lang.s("chat.liveConnecting")
        case .listening:         return live.working ? lang.s("chat.liveThinking")
                                                     : lang.s("chat.liveListening")
        case .speaking:          return lang.s("chat.liveSpeaking")
        }
    }

    private var glow: Double {
        switch live.phase {
        case .listening:         return 0.40
        case .speaking:          return 0.55
        case .connecting, .idle: return 0.20
        }
    }

    private var pulseLow: CGFloat { live.phase == .connecting ? 0.92 : 0.85 }
    private var pulseHigh: CGFloat { live.phase == .speaking ? 1.12 : 1.02 }
    private var pulseSpeed: Double { live.phase == .speaking ? 0.7 : 1.8 }
}

/// The call going on while its screen is closed: tap to go back to it, or hang up.
struct CallBar: View {
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var live: GeminiLiveManager
    let open: () -> Void

    var body: some View {
        HStack(spacing: Theme.Spacing.md) {
            Image(systemName: live.phase == .speaking ? "waveform" : "phone.fill")
                .symbolEffect(.variableColor.iterative, isActive: live.phase == .speaking)
                .foregroundColor(Theme.Colors.onFill)
            Text(lang.s("chat.liveBar"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.onFill)
            Spacer(minLength: 0)
            Button { live.stop() } label: {
                Image(systemName: "phone.down.fill")
                    .foregroundColor(Theme.Colors.onFill)
                    .padding(8)
                    .background(Circle().fill(Theme.Colors.danger))
            }
            .accessibilityLabel(lang.s("chat.liveEnd"))
        }
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.vertical, 8)
        .background(Capsule().fill(Theme.Colors.success.opacity(0.92)))
        .contentShape(Capsule())
        .onTapGesture(perform: open)
        .padding(.horizontal, Theme.Spacing.lg)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}
