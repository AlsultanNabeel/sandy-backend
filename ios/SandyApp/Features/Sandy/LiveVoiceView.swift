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

    @StateObject private var live = GeminiLiveManager()

    /// نبضة الهالة المستمرة.
    @State private var pulse = false

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: Theme.Spacing.xl) {
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
            live.start(baseURL: state.api.baseURL, token: state.api.token ?? "")
        }
        .onDisappear { live.stop() }
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
                .animation(.easeInOut(duration: pulseSpeed).repeatForever(autoreverses: true), value: pulse)

            SandyRobot(size: 168,
                       blink: false,
                       happy: true,
                       animated: true,
                       mouthOpen: live.mouthOpen)
                .scaleEffect(live.phase == .speaking ? 1.04 : 1.0)
                .animation(.easeInOut(duration: 0.3), value: live.phase)
        }
        .frame(height: 320)
    }

    // MARK: - جملة الحالة

    private var statusLabel: some View {
        Text(statusText)
            .font(Theme.Typography.title)
            .foregroundColor(Theme.Colors.primaryText)
            .animation(.easeInOut(duration: 0.2), value: live.phase)
    }

    // MARK: - تلميح / خطأ

    @ViewBuilder
    private var captions: some View {
        VStack(spacing: Theme.Spacing.md) {
            if live.permissionDenied {
                Text(lang.s("chat.voiceDenied"))
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.warn)
                    .multilineTextAlignment(.center)
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
        .animation(.easeInOut(duration: 0.25), value: live.phase)
        .animation(.easeInOut(duration: 0.25), value: live.errorText)
    }

    // MARK: - زر الإنهاء

    private var endButton: some View {
        Button { dismiss() } label: {
            HStack(spacing: Theme.Spacing.sm) {
                Image(systemName: "phone.down.fill")
                Text(lang.s("chat.liveEnd"))
                    .font(Theme.Typography.button)
            }
            .foregroundColor(.white)
            .padding(.vertical, Theme.Spacing.md)
            .padding(.horizontal, Theme.Spacing.xl)
            .background(Color(red: 0.93, green: 0.27, blue: 0.33))
            .clipShape(Capsule())
            .shadow(color: Color(red: 0.93, green: 0.27, blue: 0.33).opacity(0.5),
                    radius: 12, x: 0, y: 4)
        }
        .buttonStyle(.plain)
    }

    // MARK: - اشتقاقات الطور

    private var statusText: String {
        switch live.phase {
        case .idle, .connecting: return lang.s("chat.liveConnecting")
        case .listening:         return lang.s("chat.liveListening")
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
