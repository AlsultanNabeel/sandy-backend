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
    @FocusState private var focused: Bool
    @State private var glow = false

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            field
            if thinking || !reply.isEmpty { answer.transition(.move(edge: .top).combined(with: .opacity)) }
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
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(Theme.Colors.accent)
                    .padding(8)
                    .onLongPressGesture(minimumDuration: 0.35) {
                        Haptics.play(.listening)
                        DeepLinkRouter.shared.pending = .call
                    }
                    .accessibilityLabel(lang.s("today.holdToTalk"))
            } else {
                Button(action: send) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 28))
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

    private var answer: some View {
        HStack(alignment: .top, spacing: Theme.Spacing.sm) {
            SandyAvatar(size: 28, mood: thinking ? .soft : .happy)
            if thinking && reply.isEmpty {
                ProgressView().tint(Theme.Colors.accent)
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
                let out = try await state.api.sendMessageStreaming(message) { partial in
                    reply = partial
                }
                reply = out.reply
            } catch {
                reply = lang.s("today.askFailed")
            }
            thinking = false
            await onDone()
        }
    }
}
