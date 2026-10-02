import SwiftUI

// Loading without spinners: grey shapes with a passing shine where content will be, a
// few soft dots inside buttons, and for a long wait Sandy herself — blinking, thinking,
// waving — with a short line that changes and calls the user by name. Under Reduce
// Motion nothing moves: the shapes stay grey and the lines still change.

// MARK: - Shine

private struct Shimmer: ViewModifier {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var phase: CGFloat = -1

    func body(content: Content) -> some View {
        content
            .overlay {
                if !reduceMotion {
                    GeometryReader { geo in
                        LinearGradient(colors: [.clear, Theme.Colors.shine.opacity(0.35), .clear],
                                       startPoint: .leading, endPoint: .trailing)
                            .frame(width: geo.size.width * 0.6)
                            .offset(x: phase * geo.size.width * 1.6)
                    }
                    .mask(content)
                    .allowsHitTesting(false)
                }
            }
            .onAppear {
                guard !reduceMotion else { return }
                withAnimation(.linear(duration: 1.3).repeatForever(autoreverses: false)) { phase = 1 }
            }
    }
}

extension View {
    /// A light passing over the shape, left to right, until it is replaced.
    func shimmering() -> some View { modifier(Shimmer()) }
}

// MARK: - Skeletons

/// One grey shape with the shine.
struct SkeletonBlock: View {
    var cornerRadius: CGFloat = Theme.Radius.control

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(Theme.Colors.surface)
            .shimmering()
            .accessibilityHidden(true)
    }
}

/// A row about to be filled: a round mark and two lines, inside a card like the real one.
struct SkeletonRow: View {
    var body: some View {
        HStack(spacing: Theme.Spacing.md) {
            Circle().fill(Theme.Colors.surface).frame(width: Theme.Icon.lg, height: Theme.Icon.lg)
            VStack(alignment: .leading, spacing: 6) {
                RoundedRectangle(cornerRadius: 4).fill(Theme.Colors.surface).frame(height: 12)
                RoundedRectangle(cornerRadius: 4).fill(Theme.Colors.surface)
                    .frame(width: 110, height: 10)
            }
            Spacer(minLength: 0)
        }
        .shimmering()
        .sandyCard()
        .accessibilityHidden(true)
    }
}

/// A list on its way: a few rows, read once as «loading».
struct SkeletonList: View {
    @EnvironmentObject var lang: LanguageManager
    var rows = 5

    var body: some View {
        VStack(spacing: Theme.Spacing.sm) {
            ForEach(0..<rows, id: \.self) { _ in SkeletonRow() }
        }
        .accessibilityElement()
        .accessibilityLabel(lang.s("loading.label"))
    }
}

// MARK: - Inside a button

/// Three soft dots that take turns, for a short wait inside a button or a chip.
struct LoadingDots: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var color: Color = Theme.Colors.accent
    @State private var on = false

    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<3, id: \.self) { i in
                Circle()
                    .fill(color)
                    .frame(width: 6, height: 6)
                    .opacity(reduceMotion ? 0.7 : (on ? 1 : 0.3))
                    .animation(reduceMotion ? nil
                               : .easeInOut(duration: 0.5).repeatForever().delay(Double(i) * 0.15),
                               value: on)
            }
        }
        .onAppear { on = true }
        .accessibilityElement()
        .accessibilityLabel(LanguageManager.shared.s("loading.label"))
    }
}

// MARK: - A long wait

/// Sandy waiting with you: she blinks, tilts as if thinking, and waves now and then,
/// while a short line changes every few seconds.
struct SandyWaiting: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// "loading.lines" (anything) or "loading.drawLines" (an image on its way).
    var linesKey = "loading.lines"
    var size: CGFloat = 72
    var compact = false
    /// Off where her face is already beside it (the ask bar's answer).
    var showsFace = true

    @State private var line = ""
    @State private var tilt = false
    @State private var wave = false

    private var name: String {
        let n = state.onboarding.preferredName.isEmpty ? state.onboarding.name : state.onboarding.preferredName
        return n.isEmpty ? lang.s("chat.friend") : n
    }

    var body: some View {
        let layout = compact ? AnyLayout(HStackLayout(spacing: Theme.Spacing.sm))
                             : AnyLayout(VStackLayout(spacing: Theme.Spacing.md))
        layout {
            if showsFace {
            SandyRobot(size: size * (110.0 / 172.0), blink: false, happy: true, animated: true)
                .frame(width: size, height: size)
                .rotationEffect(.degrees(reduceMotion ? 0 : (tilt ? -7 : 5)))
                .overlay(alignment: .topTrailing) {
                    Text("👋")
                        .scaledFont(size * 0.28)
                        .rotationEffect(.degrees(wave ? 18 : -12), anchor: .bottomLeading)
                        .opacity(reduceMotion ? 0 : (wave ? 1 : 0))
                }
                .accessibilityHidden(true)
            }
            Text(line)
                .font(compact ? Theme.Typography.caption : Theme.Typography.callout)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(compact ? .leading : .center)
                .fixedSize(horizontal: false, vertical: true)
                .contentTransition(.opacity)
                .id(line)
                .transition(.opacity)
        }
        .frame(maxWidth: compact ? nil : .infinity)
        .accessibilityElement(children: .combine)
        .task { await cycle() }
    }

    /// A new line every three seconds (never the same one twice in a row); a wave now and then.
    private func cycle() async {
        let lines = lang.list(linesKey)
        guard !lines.isEmpty else { return }
        var last = -1
        if !reduceMotion {
            withAnimation(.easeInOut(duration: 1.6).repeatForever(autoreverses: true)) { tilt = true }
        }
        while !Task.isCancelled {
            var pick = Int.random(in: 0..<lines.count)
            if lines.count > 1 && pick == last { pick = (pick + 1) % lines.count }
            last = pick
            withAnimation(Animation.easeInOut(duration: 0.3).reduced) {
                line = String(format: lines[pick], name)
            }
            if !reduceMotion && Bool.random() {
                withAnimation(.easeInOut(duration: 0.25).repeatCount(4, autoreverses: true)) { wave = true }
                try? await Task.sleep(for: .seconds(1.2))
                withAnimation(.easeOut(duration: 0.2)) { wave = false }
                try? await Task.sleep(for: .seconds(1.8))
            } else {
                try? await Task.sleep(for: .seconds(3))
            }
        }
    }
}
