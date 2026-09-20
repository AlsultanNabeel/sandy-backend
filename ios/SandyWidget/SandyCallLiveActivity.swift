//
//  SandyCallLiveActivity.swift — مكالمة ساندي الصوتية على شاشة القفل والجزيرة الديناميكية.
//
//  يبدأها التطبيق (App/Widgets/CallLiveActivity.swift) لما تبلّش المكالمة، ويحدّثها
//  مع كل تغيّر بالطور، وينهيها فورًا لما تخلص. اللغة والاتجاه من `isArabic`.
//

import ActivityKit
import SwiftUI
import WidgetKit

private let endRed = Color(red: 0.93, green: 0.27, blue: 0.33)

private extension SandyCallAttributes.Phase {
    func title(arabic: Bool) -> String {
        switch self {
        case .connecting: return arabic ? "عم توصل…" : "Connecting…"
        case .listening:  return arabic ? "عم تسمع" : "Listening"
        case .speaking:   return arabic ? "عم تحكي" : "Speaking"
        }
    }

    var icon: String {
        switch self {
        case .connecting: return "antenna.radiowaves.left.and.right"
        case .listening:  return "mic.fill"
        case .speaking:   return "waveform"
        }
    }
}

/// Sandy's glyph: sparkles on a cyan disc.
private struct SandyGlyph: View {
    var size: CGFloat
    var body: some View {
        ZStack {
            Circle().fill(LinearGradient(colors: [.cyan, .blue],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
            Image(systemName: "sparkles")
                .font(.system(size: size * 0.48, weight: .semibold))
                .foregroundStyle(.white)
        }
        .frame(width: size, height: size)
    }
}

/// The running call time, counting up from the call start.
private struct CallTimer: View {
    let startedAt: Date
    var body: some View {
        Text(timerInterval: startedAt...startedAt.addingTimeInterval(6 * 3600), countsDown: false)
            .monospacedDigit()
    }
}

/// End-call button: opens `sandy://call/end`, which ends the call in the app.
private struct EndCallLink: View {
    let arabic: Bool
    var compact = false
    var body: some View {
        Link(destination: SandyLinks.endCall) {
            HStack(spacing: 6) {
                Image(systemName: "phone.down.fill")
                if !compact {
                    Text(arabic ? "إنهاء" : "End").font(.system(size: 14, weight: .semibold))
                }
            }
            .foregroundStyle(.white)
            .padding(.horizontal, compact ? 10 : 14)
            .frame(height: 36)
            .background(Capsule().fill(endRed))
        }
        .accessibilityLabel(arabic ? "إنهاء المكالمة" : "End call")
    }
}

struct SandyCallLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: SandyCallAttributes.self) { context in
            // شاشة القفل / البانر.
            let ar = context.attributes.isArabic
            HStack(spacing: 12) {
                SandyGlyph(size: 44)
                VStack(alignment: .leading, spacing: 2) {
                    Text(ar ? "ساندي" : "Sandy")
                        .font(.caption).foregroundStyle(.secondary)
                    Label(context.state.phase.title(arabic: ar),
                          systemImage: context.state.phase.icon)
                        .font(.headline)
                        .foregroundStyle(.white)
                    CallTimer(startedAt: context.state.startedAt)
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                EndCallLink(arabic: ar, compact: true)
            }
            .padding(16)
            .environment(\.layoutDirection, ar ? .rightToLeft : .leftToRight)
            .environment(\.locale, Locale(identifier: ar ? "ar" : "en"))
            .activityBackgroundTint(Color.black.opacity(0.85))
            .activitySystemActionForegroundColor(.cyan)
        } dynamicIsland: { context in
            let ar = context.attributes.isArabic
            let dir: LayoutDirection = ar ? .rightToLeft : .leftToRight
            let locale = Locale(identifier: ar ? "ar" : "en")
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    HStack(spacing: 8) {
                        SandyGlyph(size: 32)
                        Text(ar ? "ساندي" : "Sandy").font(.headline)
                    }
                    .environment(\.layoutDirection, dir)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    CallTimer(startedAt: context.state.startedAt)
                        .font(.headline)
                        .foregroundStyle(.cyan)
                        .frame(maxWidth: 80)
                        .environment(\.locale, locale)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    HStack {
                        Label(context.state.phase.title(arabic: ar),
                              systemImage: context.state.phase.icon)
                            .font(.subheadline.weight(.semibold))
                        Spacer(minLength: 0)
                        EndCallLink(arabic: ar)
                    }
                    .padding(.top, 4)
                    .environment(\.layoutDirection, dir)
                }
            } compactLeading: {
                SandyGlyph(size: 22)
            } compactTrailing: {
                CallTimer(startedAt: context.state.startedAt)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.cyan)
                    .frame(maxWidth: 44)
                    .environment(\.locale, locale)
            } minimal: {
                Image(systemName: context.state.phase.icon)
                    .foregroundStyle(.cyan)
            }
            .keylineTint(.cyan)
        }
    }
}
