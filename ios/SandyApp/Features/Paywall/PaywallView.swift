import SwiftUI

/// شاشة الاشتراك (المرحلة السابعة). تعرض المزايا + السعر + زر الشراء والاسترجاع.
///
/// تشتغل هلأ بدون حزمة RevenueCat: لو الشراء مش متاح (`purchasesAvailable == false`)
/// بتعرض ملاحظة لطيفة وبتعطّل الزر — وأول ما تُضاف الحزمة والمفتاح بيشتغل الشراء
/// بلا تعديل. لو المستخدم مشترك أصلًا بتعرض حالة الشكر.
struct PaywallView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var subs: SubscriptionManager
    @Environment(\.dismiss) private var dismiss

    private let features = ["paywall.feature.nudge", "paywall.feature.voice",
                            "paywall.feature.memory", "paywall.feature.tools"]

    var body: some View {
        ZStack {
            SandyBackground()
            ScrollView {
                VStack(spacing: Theme.Spacing.lg) {
                    header
                    if subs.isSubscriber {
                        subscribedCard
                    } else {
                        featuresCard
                        purchaseSection
                    }
                }
                .padding(Theme.Spacing.md)
            }
        }
        .navigationTitle(lang.s("paywall.title"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button(lang.s("common.done")) { dismiss() }
            }
        }
        .task { await subs.refresh(api: state.api) }
    }

    private var header: some View {
        VStack(spacing: Theme.Spacing.sm) {
            SandyRobot(size: 88, happy: true, animated: true)
            Text(lang.s("paywall.title"))
                .font(Theme.Typography.title)
                .foregroundColor(Theme.Colors.primaryText)
            Text(lang.s("paywall.tagline"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, Theme.Spacing.md)
    }

    private var featuresCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                ForEach(features, id: \.self) { key in
                    HStack(spacing: Theme.Spacing.md) {
                        Image(systemName: "checkmark.seal.fill")
                            .foregroundColor(Theme.Colors.accent)
                        Text(lang.s(key))
                            .font(Theme.Typography.body)
                            .foregroundColor(Theme.Colors.primaryText)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }
                }
            }
        }
    }

    private var purchaseSection: some View {
        VStack(spacing: Theme.Spacing.md) {
            // السعر من المتجر لو متوفّر، وإلا نص بديل.
            Text(subs.priceText.isEmpty ? lang.s("paywall.priceFallback") : subs.priceText)
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.accentSoft)

            SandyButton(title: lang.s("paywall.cta"),
                        systemImage: "sparkles",
                        isLoading: subs.busy,
                        fillWidth: true) {
                Task { await subs.purchase(api: state.api) }
            }
            .disabled(!subs.purchasesAvailable)
            .opacity(subs.purchasesAvailable ? 1 : 0.5)

            if subs.purchasesAvailable {
                Button(lang.s("paywall.restore")) {
                    Task { await subs.restore(api: state.api) }
                }
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
            } else {
                // الحزمة/المفتاح لسّا مش جاهزين — نطمّن المستخدم بدل زر ميت صامت.
                SandyNotice(lang.s("paywall.soon"), kind: .info)
            }

            Text(lang.s("paywall.terms"))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.tertiaryText)
                .multilineTextAlignment(.center)
        }
    }

    private var subscribedCard: some View {
        SandyCard {
            VStack(spacing: Theme.Spacing.sm) {
                Text(lang.s("paywall.subscribed"))
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.accent)
                Text(lang.s("paywall.subscribedSub"))
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.secondaryText)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, Theme.Spacing.sm)
        }
    }
}
