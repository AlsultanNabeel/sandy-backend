import Foundation

// Namespace: paywall — the subscription screen (PaywallView). Phase 7.
enum L10nPaywall {
    static let ns = "paywall"

    static let table = L10nTable(
        ar: [
            "title":        .text("ساندي بريميوم"),
            "tagline":      .text("ساندي كاملة معك، كل يوم."),
            "feature.nudge":   .text("تنبيه يومي ذكي بشخصية ساندي"),
            "feature.voice":   .text("محادثة صوتية طبيعية بلا حدود"),
            "feature.memory":  .text("ذاكرة تتذكّر كل تفاصيلك"),
            "feature.tools":   .text("كل الأدوات: مهام، مصاريف، صور، وأكثر"),
            "cta":          .text("اشترك الآن"),
            "restore":      .text("استرجاع الاشتراك"),
            "subscribed":   .text("أنت مشترك ✓"),
            "subscribedSub": .text("شكراً إنك معنا 🌿"),
            "soon":         .text("الدفع بينفتح قريباً — بنجهّزه."),
            "priceFallback": .text("اشتراك شهري"),
            "terms":        .text("يتجدّد شهرياً تلقائياً. تقدر تلغي أي وقت من إعدادات آبل."),
        ],
        en: [
            "title":        .text("Sandy Premium"),
            "tagline":      .text("All of Sandy, with you every day."),
            "feature.nudge":   .text("A smart daily nudge in Sandy's voice"),
            "feature.voice":   .text("Unlimited natural voice conversation"),
            "feature.memory":  .text("Memory that remembers all your details"),
            "feature.tools":   .text("Every tool: tasks, expenses, images, and more"),
            "cta":          .text("Subscribe now"),
            "restore":      .text("Restore purchase"),
            "subscribed":   .text("You're subscribed ✓"),
            "subscribedSub": .text("Thanks for being here 🌿"),
            "soon":         .text("Payments open soon — we're getting it ready."),
            "priceFallback": .text("Monthly subscription"),
            "terms":        .text("Auto-renews monthly. Cancel anytime in Apple settings."),
        ]
    )
}
