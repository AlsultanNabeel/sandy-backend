import SwiftUI

/// Asks for the ask bar to take the keyboard (the quick-add shortcut and widget use it).
@MainActor
final class AskBarFocus: ObservableObject {
    static let shared = AskBarFocus()
    @Published var request = 0
}

/// «شو ببالك؟» — one field for everything. Sandy decides whether it is a task, a
/// reminder or an expense, answers right under it, and the day below refreshes.
/// Holding the mic opens the live call.
struct AskBar: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject private var focusRequests = AskBarFocus.shared
    let onDone: () async -> Void

    @State private var text = ""
    @State private var reply = ""
    @State private var thinking = false
    @State private var activity = ""
    /// The mic was held while it is off for the app: say so, with the way to Settings.
    @State private var micBlocked = false
    @FocusState private var focused: Bool
    @State private var glow = false

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            field
            if micBlocked { PermissionCard(kind: .mic) }
            if thinking || !reply.isEmpty {
                answer.transition(.move(edge: .top).combined(with: .opacity))
            } else if text.isEmpty {
                suggestions.transition(.opacity)
            }
        }
        .animation(.spring(response: 0.45, dampingFraction: 0.85), value: reply)
        .animation(.spring(response: 0.45, dampingFraction: 0.85), value: thinking)
        .onChange(of: focusRequests.request) { focused = true }
        .onAppear { glow = true }
    }

    private var field: some View {
        HStack(spacing: Theme.Spacing.sm) {
            Image(systemName: "sparkles")
                .foregroundColor(Theme.Colors.accent)
            TextField(lang.s("today.ask"), text: $text, axis: .vertical)
                .lineLimit(1...4)
                .focused($focused)
                .submitLabel(.send)
                .onSubmit(send)
            if trimmed.isEmpty {
                Image(systemName: "mic.fill")
                    .scaledFont(Theme.Icon.md, weight: .semibold)
                    .foregroundColor(Theme.Colors.accent)
                    .padding(8)
                    .onLongPressGesture(minimumDuration: 0.35) {
                        if Permissions.shared.micDenied {
                            withAnimation { micBlocked = true }
                            return
                        }
                        Haptics.play(.listening)
                        DeepLinkRouter.shared.pending = .call
                    }
                    .accessibilityLabel(lang.s("today.holdToTalk"))
            } else {
                Button(action: send) {
                    Image(systemName: "arrow.up.circle.fill")
                        .scaledFont(28, relativeTo: .largeTitle)
                        .foregroundColor(Theme.Colors.accent)
                }
                .disabled(thinking)
            }
        }
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.vertical, Theme.Spacing.sm)
        .liquidGlass(cornerRadius: 22, tint: 0.10, shine: 0.3)
        .overlay(
            // A light that keeps travelling round the edge: the one live thing on the screen.
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(AngularGradient(
                    colors: [Theme.Colors.accent, Theme.Colors.accentDeep.opacity(0.1),
                             Theme.Colors.success.opacity(0.6), Theme.Colors.accent],
                    center: .center, angle: .degrees(glow ? 360 : 0)), lineWidth: 1.5)
                .animation(.linear(duration: 6).repeatForever(autoreverses: false), value: glow)
        )
        .shadow(color: Theme.Colors.accent.opacity(focused ? 0.35 : 0.15), radius: 16)
    }

    /// Starts of sentences Sandy understands: they teach what the field can do.
    private var suggestions: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Theme.Spacing.sm) {
                ForEach(lang.list("today.suggestions"), id: \.self) { start in
                    Button {
                        text = start + " "
                        focused = true
                    } label: {
                        Text(start)
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                            .padding(.horizontal, Theme.Spacing.md)
                            .padding(.vertical, 7)
                            .background(Capsule().stroke(Theme.Colors.border, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var answer: some View {
        HStack(alignment: .top, spacing: Theme.Spacing.sm) {
            SandyAvatar(size: 28, mood: thinking ? .soft : .happy)
            if thinking && reply.isEmpty {
                HStack(spacing: Theme.Spacing.sm) {
                    ProgressView().tint(Theme.Colors.accent)
                    if !activity.isEmpty {
                        Text(activity)
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                }
            } else {
                Text(reply)
                    .font(Theme.Typography.body)
                    .foregroundColor(Theme.Colors.primaryText)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            if !thinking {
                Button { reply = "" } label: {
                    Image(systemName: "xmark").font(.caption).foregroundColor(Theme.Colors.tertiaryText)
                }
            }
        }
        .padding(Theme.Spacing.md)
        .background(RoundedRectangle(cornerRadius: 18).fill(Theme.Colors.surface.opacity(0.55)))
    }

    private func send() {
        let message = trimmed
        guard !message.isEmpty, !thinking else { return }
        text = ""
        reply = ""
        thinking = true
        focused = false
        Haptics.play(.send)
        Task {
            do {
                let out = try await state.api.sendMessageStreaming(message, onStep: { step in
                    activity = ChatStep.label(step)
                }) { partial in
                    reply = partial
                }
                reply = out.reply
            } catch {
                reply = lang.s("today.askFailed")
            }
            thinking = false
            activity = ""
            await onDone()
        }
    }
}
