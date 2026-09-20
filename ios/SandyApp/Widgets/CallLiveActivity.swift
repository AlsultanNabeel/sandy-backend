import ActivityKit
import Foundation

/// The live voice call on the Lock Screen and in the Dynamic Island.
///
/// `GeminiLiveManager` reports every real phase transition here: the activity
/// starts when the call starts connecting (the app is in the foreground then, as
/// ActivityKit requires), is updated when the phase changes, and ends — dismissed
/// immediately — the moment the call goes idle (user stop, error, dropped socket).
@MainActor
final class CallLiveActivity {
    static let shared = CallLiveActivity()

    private var activity: Activity<SandyCallAttributes>?
    private var lastPhase: SandyCallAttributes.Phase?
    private var startedAt = Date()

    /// True while a call is connecting or connected (independent of whether
    /// Live Activities are allowed), so a second `sandy://call` is ignored.
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

    /// Ends the call's activity right away (no lingering banner).
    func end() {
        lastPhase = nil
        guard let activity else { return }
        self.activity = nil
        Task { await activity.end(nil, dismissalPolicy: .immediate) }
    }

    /// At launch no call is running: anything still on screen was left behind
    /// by a previous run that was killed mid-call.
    static func endStale() {
        Task {
            for stale in Activity<SandyCallAttributes>.activities {
                await stale.end(nil, dismissalPolicy: .immediate)
            }
        }
    }
}
