import SwiftUI

/// تبويب حياتي — لوح ودجات زي «يومي»، مش قائمة ثابتة.
/// العادات انتقلت لتبويب يومي.
struct LifeView: View {
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store = DashboardStore(id: "life", catalog: LifeView.catalog)

    /// ميزات «حياتي» كودجات — نفس لوح «يومي».
    ///
    /// كانت قائمة ثابتة بثلاث صفوف بنفس الحجم بنفس الترتيب للكل. اللي بيسجّل
    /// مصاريفه كل يوم واليوميات مرّة بالشهر بده الأولى كبيرة والتانية مربّع —
    /// والترتيب اللي اخترته أنا تخمين عن الناس، مش معرفة عنه هو.
    static let catalog: [WidgetSpec] = [
        WidgetSpec(key: "expenses", icon: "creditcard.fill", titleKey: "life.expenses",
                   tint: Theme.Colors.success, defaultCols: 2) { AnyView(ExpensesView()) },
        WidgetSpec(key: "journal", icon: "book.closed.fill", titleKey: "life.journal",
                   tint: Theme.Colors.warn, defaultCols: 2) { AnyView(JournalView()) },
        WidgetSpec(key: "gifts", icon: "gift.fill", titleKey: "life.gifts",
                   tint: Theme.Colors.accent, defaultCols: 2) { AnyView(GiftsView()) },
    ]

    var body: some View {
        WidgetDashboard(store: store)
            .navigationTitle(lang.s("life.title"))
    }
}

// MARK: - العادات

// MARK: - المصاريف

// MARK: - اليوميات

// MARK: - حالة فاضية حيّة (مشتركة)

/// حالة فاضية ودودة: أفاتار ساندي + سطر تشجيع عربي — بدل أيقونة باهتة.
/// تطفو بنعومة لتعطي إحساس بالحياة.
struct LivelyEmptyState: View {
    let line: String
    var mood: SandyAvatar.Mood = .happy

    @State private var bob = false

    var body: some View {
        VStack(spacing: Theme.Spacing.md) {
            SandyAvatar(size: 64, mood: mood)
                .offset(y: bob ? -6 : 0)
                .animation(.easeInOut(duration: 2.2).repeatForever(autoreverses: true), value: bob)
            Text(line)
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Spacing.xl)
        .onAppear { bob = true }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// MARK: - الستورات (مصدر الحقيقة لكل قسم)
//
// كل ستور يملك بياناته + الجلب + التعديلات، مستقل عن دورة حياة الشاشة. الجلب
// بمهمة مملوكة للستور، فإلغاء إيماءة السحب/التنقّل ما يلغيه — والجديد يبيّن دايماً.
