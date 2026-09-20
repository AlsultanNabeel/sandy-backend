//
//  SandyFocusLiveActivity.swift — جلسة التركيز على شاشة القفل والجزيرة الديناميكية.
//
//  يبدأها التطبيق (SandyApp/Widgets/FocusLiveActivity.swift) لما تبلّش الجلسة،
//  ويحدّثها مع كل تغيّر طور، وينهيها لما تخلص. العدّ التنازلي بيرسمه النظام من
//  المدى الزمني، فبيمشي والتطبيق نايم. اللغة والاتجاه من `isArabic`.
//

import ActivityKit
import SwiftUI
import WidgetKit

private let focusCyan = Color.cyan
private let breakAmber = Color(red: 1.0, green: 0.72, blue: 0.28)

private extension SandyFocusAttributes.ContentState {
    var tint: Color { isBreak ? breakAmber : focusCyan }
    var icon: String { isBreak ? "cup.and.saucer.fill" : "brain.head.profile" }

    /// مدى العدّ — مضمون مرتّب حتى لو وصلت أرقام غريبة.
    var range: ClosedRange<Date> {
        phaseStartedAt <= phaseEndsAt ? phaseStartedAt...phaseEndsAt : phaseEndsAt...phaseEndsAt
    }

    func phaseTitle(arabic: Bool) -> String {
        if isBreak { return arabic ? "استراحة" : "Break" }
        return arabic ? "تركيز" : "Focus"
    }

    /// «الدورة ٢ من ٤» بأرقام لغة التطبيق.
    func cycleText(arabic: Bool) -> String {
        let f = NumberFormatter()
        f.locale = Locale(identifier: arabic ? "ar" : "en")
        let c = f.string(from: NSNumber(value: cycle)) ?? String(cycle)
        let n = f.string(from: NSNumber(value: cycles)) ?? String(cycles)
        return arabic ? "الدورة \(c) من \(n)" : "Cycle \(c) of \(n)"
    }
}

private extension SandyFocusAttributes {
    func title(_ state: ContentState) -> String {
        let t = label.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? state.phaseTitle(arabic: isArabic) : t
    }
}

/// العدّ التنازلي للطور الحالي.
private struct FocusCountdown: View {
    let state: SandyFocusAttributes.ContentState
    var body: some View {
        Text(timerInterval: state.range, countsDown: true)
            .monospacedDigit()
            .multilineTextAlignment(.center)
    }
}

/// زر الإنهاء: يفتح `sandy://focus/stop`، والتطبيق بينهي الجلسة.
private struct StopFocusLink: View {
    let arabic: Bool
    var compact = false
    var body: some View {
        Link(destination: SandyFocusLinks.stop) {
            HStack(spacing: 6) {
                Image(systemName: "stop.fill")
                if !compact {
                    Text(arabic ? "إنهاء" : "Stop").font(.system(size: 14, weight: .semibold))
                }
            }
            .foregroundStyle(.white)
            .padding(.horizontal, compact ? 12 : 14)
            .frame(height: 36)
            .background(Capsule().fill(Color.white.opacity(0.18)))
        }
        .accessibilityLabel(arabic ? "إنهاء جلسة التركيز" : "Stop focus session")
    }
}

/// أيقونة الطور على قرص ملوّن.
private struct FocusGlyph: View {
    let state: SandyFocusAttributes.ContentState
    var size: CGFloat
    var body: some View {
        ZStack {
            Circle().fill(state.tint.opacity(0.22))
            Image(systemName: state.icon)
                .font(.system(size: size * 0.46, weight: .semibold))
                .foregroundStyle(state.tint)
        }
        .frame(width: size, height: size)
    }
}

struct SandyFocusLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: SandyFocusAttributes.self) { context in
            // شاشة القفل / البانر.
            let ar = context.attributes.isArabic
            let st = context.state
            VStack(spacing: 10) {
                HStack(spacing: 12) {
                    FocusGlyph(state: st, size: 44)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(context.attributes.title(st))
                            .font(.headline)
                            .foregroundStyle(.white)
                            .lineLimit(1)
                        Text(st.phaseTitle(arabic: ar) + " · " + st.cycleText(arabic: ar))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                    FocusCountdown(state: st)
                        .font(.system(size: 30, weight: .bold, design: .rounded))
                        .foregroundStyle(st.tint)
                        .frame(maxWidth: 110)
                }
                HStack {
                    ProgressView(timerInterval: st.range, countsDown: true) {
                        EmptyView()
                    } currentValueLabel: {
                        EmptyView()
                    }
                    .tint(st.tint)
                    StopFocusLink(arabic: ar, compact: true)
                }
            }
            .padding(16)
            .environment(\.layoutDirection, ar ? .rightToLeft : .leftToRight)
            .environment(\.locale, Locale(identifier: ar ? "ar" : "en"))
            .activityBackgroundTint(Color.black.opacity(0.85))
            .activitySystemActionForegroundColor(focusCyan)
        } dynamicIsland: { context in
            let ar = context.attributes.isArabic
            let st = context.state
            let dir: LayoutDirection = ar ? .rightToLeft : .leftToRight
            let locale = Locale(identifier: ar ? "ar" : "en")
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    HStack(spacing: 8) {
                        FocusGlyph(state: st, size: 32)
                        Text(st.phaseTitle(arabic: ar)).font(.headline)
                    }
                    .environment(\.layoutDirection, dir)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    FocusCountdown(state: st)
                        .font(.title3.weight(.bold))
                        .foregroundStyle(st.tint)
                        .frame(maxWidth: 90)
                        .environment(\.locale, locale)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(context.attributes.title(st))
                                .font(.subheadline.weight(.semibold))
                                .lineLimit(1)
                            Text(st.cycleText(arabic: ar))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 0)
                        StopFocusLink(arabic: ar)
                    }
                    .padding(.top, 4)
                    .environment(\.layoutDirection, dir)
                    .environment(\.locale, locale)
                }
            } compactLeading: {
                Image(systemName: st.icon)
                    .foregroundStyle(st.tint)
            } compactTrailing: {
                FocusCountdown(state: st)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(st.tint)
                    .frame(maxWidth: 44)
                    .environment(\.locale, locale)
            } minimal: {
                ProgressView(timerInterval: st.range, countsDown: true) {
                    EmptyView()
                } currentValueLabel: {
                    Image(systemName: st.icon).font(.system(size: 9, weight: .bold))
                }
                .progressViewStyle(.circular)
                .tint(st.tint)
            }
            .widgetURL(URL(string: "sandy://focus"))
            .keylineTint(st.tint)
        }
    }
}
