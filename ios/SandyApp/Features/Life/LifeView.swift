import SwiftUI

/// تبويب حياتي — لوحة فيها روابط لـ المصاريف/اليوميات (بدل زحمة التبويبات).
/// العادات انتقلت لتبويب يومي. تستعمل نمط الهَب المشترك (HubList) — تنضاف لها
/// الهدايا الرقمية والألبومات لاحقاً.
struct LifeView: View {
    @EnvironmentObject var lang: LanguageManager

    private let rows: [HubRowSpec] = [
        HubRowSpec(icon: "creditcard.fill", titleKey: "life.expenses",
                   subtitleKey: "life.expenses.subtitle", tint: Theme.Colors.success),
        HubRowSpec(icon: "book.closed.fill", titleKey: "life.journal",
                   subtitleKey: "life.journal.subtitle", tint: Theme.Colors.warn),
        HubRowSpec(icon: "gift.fill", titleKey: "life.gifts",
                   subtitleKey: "life.gifts.subtitle", tint: Theme.Colors.accent),
    ]

    var body: some View {
        HubList(rows: rows) { index in
            switch index {
            case 0:  ExpensesView()
            case 1:  JournalView()
            default: GiftsView()
            }
        }
        .navigationTitle(lang.s("life.title"))
    }
}

// MARK: - العادات



// MARK: - المصاريف



// MARK: - اليوميات



// MARK: - حالة فاضية حيّة (مشتركة)

/// حالة فاضية ودودة: أفاتار ساندي + سطر تشجيع عربي — بدل أيقونة باهتة.
/// تطفو بنعومة لتعطي إحساس بالحياة.
private struct LivelyEmptyState: View {
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
