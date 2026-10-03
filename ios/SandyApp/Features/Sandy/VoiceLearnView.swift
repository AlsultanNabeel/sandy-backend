import SwiftUI

/// «صوتي»: whether she knows the owner's voice, and teaching it to her from the robot's own
/// mic (`/api/voice/enroll`). The clips are the next robot turns; this screen only starts it
/// and follows along.
struct VoiceLearnView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @State private var status: VoiceEnrollStatus?
    @State private var failed = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                SandyCard {
                    VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                        if let s = status {
                            Label(lang.s(s.enrolled ? "robot.voice.known" : "robot.voice.unknown"),
                                  systemImage: s.enrolled ? "checkmark.seal.fill" : "person.fill.questionmark")
                                .foregroundColor(s.enrolled ? Theme.Colors.success : Theme.Colors.primaryText)
                            if let n = s.collecting {
                                Text(String(format: lang.s("robot.voice.progress"),
                                            AppLocale.number(n), AppLocale.number(s.needed)))
                                    .font(Theme.Typography.headline)
                                    .foregroundColor(Theme.Colors.accent)
                            }
                        } else {
                            SkeletonList(rows: 1)
                        }
                        Text(lang.s("robot.voice.howto"))
                            .font(Theme.Typography.subheadline)
                            .foregroundColor(Theme.Colors.secondaryText)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                if failed {
                    SandyNotice(lang.s("robot.voice.failed"), kind: .gentleWarning)
                }
                if status?.collecting == nil {
                    Button(lang.s(status?.enrolled == true ? "robot.voice.again" : "robot.voice.start")) {
                        Task { await start() }
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
            .padding(Theme.Spacing.md)
        }
        .background(SandyBackground())
        .navigationTitle(lang.s("robot.hub.voice"))
        // Followed while learning: each robot turn moves it on.
        .task {
            while !Task.isCancelled {
                await load()
                try? await Task.sleep(nanoseconds: status?.collecting == nil ? 30_000_000_000 : 3_000_000_000)
            }
        }
    }

    private func load() async {
        if let s = try? await state.api.voiceEnrollStatus() { status = s }
    }

    private func start() async {
        do {
            try await state.api.startVoiceEnroll()
            failed = false
            await load()
        } catch {
            failed = true
        }
    }
}

/// What `GET /api/voice/enroll` answers.
struct VoiceEnrollStatus: Decodable {
    let enrolled: Bool
    let collecting: Int?
    let needed: Int
}

extension APIClient {
    func voiceEnrollStatus() async throws -> VoiceEnrollStatus {
        try await fetch("/api/voice/enroll")
    }

    func startVoiceEnroll() async throws {
        struct Reply: Decodable { let ok: Bool? }
        let _: Reply = try await fetch("/api/voice/enroll", method: "POST")
    }
}
