import SwiftUI

/// شريط صغير «بدون إنترنت — آخر نسخة محفوظة» فوق القوائم لمّا الستور بيعرض
/// نسخة الكاش. الاستعمال:  `if store.offline { OfflineBanner() }`
struct OfflineBanner: View {
    @EnvironmentObject var lang: LanguageManager

    var body: some View {
        HStack(spacing: Theme.Spacing.xs) {
            Image(systemName: "wifi.slash")
                .font(.system(size: 12, weight: .semibold))
                .accessibilityHidden(true)
            Text(lang.s("common.offlineBanner"))
                .font(Theme.Typography.caption)
        }
        .foregroundColor(Theme.Colors.warn)
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.vertical, Theme.Spacing.xs + 2)
        .background(Capsule().fill(Theme.Colors.warnSoft))
        .overlay(Capsule().stroke(Theme.Colors.warn.opacity(0.35), lineWidth: 1))
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
        .transition(.opacity.combined(with: .move(edge: .top)))
    }
}
