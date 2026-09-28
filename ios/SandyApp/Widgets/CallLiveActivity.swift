import ActivityKit
import Foundation

/// The call's Live Activity, driven by `GeminiLiveManager` phase changes; dismissed at once when idle.
@MainActor
final class CallLiveActivity {
    static let shared = CallLiveActivity()

    private var activity: Activity<SandyCallAttributes>?
    private var lastPhase: SandyCallAttributes.Phase?
    private var startedAt = Date()

    /// Connecting or connected (even if Live Activities are off), so a second `sandy://call` is ignored.
    private(set) var isCallRunning = false

    func phaseChanged(_ phase: GeminiLiveManager.Phase) {
        switch phase {
        case .idle:       isCallRunning = false; end()
        case .connecting: isCallRunning = true; show(.connecting)
        case .listening:  isCallRunning = true; show(.listening)
        case .speaking:   isCallRunning = true; show(.speaking)
        }
    }

    private func show(_ phase: SandyCallAttributes.Phase) {
        guard phase != lastPhase else { return }
        lastPhase = phase

        if let activity {
            let content = ActivityContent(
                state: SandyCallAttributes.ContentState(phase: phase, startedAt: startedAt),
                staleDate: nil)
            Task { await activity.update(content) }
            return
        }

        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        startedAt = Date()
        let content = ActivityContent(
            state: SandyCallAttributes.ContentState(phase: phase, startedAt: startedAt),
            staleDate: nil)
        activity = try? Activity.request(
            attributes: SandyCallAttributes(isArabic: AppLocale.isArabic),
            content: content,
            pushType: nil)
    }

    func end() {
        lastPhase = nil
        guard let activity else { return }
        self.activity = nil
        Task { await activity.end(nil, dismissalPolicy: .immediate) }
    }

    /// A killed run can leave a call activity on screen; no call runs at launch.
    static func endStale() {
        Task {
            for stale in Activity<SandyCallAttributes>.activities {
                await stale.end(nil, dismissalPolicy: .immediate)
            }
        }
    }
}
