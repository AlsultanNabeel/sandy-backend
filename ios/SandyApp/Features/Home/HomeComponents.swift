import SwiftUI

/// بطاقة لمحة صغيرة: أيقونة ملوّنة + رقم بارز + وصف + تلميح اختياري.
/// النقر يبدّل للتبويب المناسب عبر closure.
struct GlanceCard: View {
    let icon: String
    let tint: Color
    let value: String
    let label: String
    var hint: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            SandyCard {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    Image(systemName: icon)
                        .font(.system(size: Theme.Icon.md, weight: .semibold))
                        .foregroundColor(tint)
                        .frame(width: 38, height: 38)
                        .background(tint.opacity(0.14))
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))

                    Text(value)
                        .font(Theme.Typography.title)
                        .foregroundColor(Theme.Colors.primaryText)
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)

                    Text(label)
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)

                    if let hint {
                        Text(hint)
                            .font(Theme.Typography.caption)
                            .foregroundColor(tint)
                            .lineLimit(1)
                            .minimumScaleFactor(0.7)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .buttonStyle(.plain)
    }
}

/// بطاقة عريضة لأقرب تذكير: أيقونة + عنوان + وصف، قابلة للنقر.
struct GlanceWideCard: View {
    let icon: String
    let tint: Color
    let title: String
    let subtitle: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            SandyCard {
                HStack(alignment: .center, spacing: Theme.Spacing.md) {
                    Image(systemName: icon)
                        .font(.system(size: Theme.Icon.md, weight: .semibold))
                        .foregroundColor(tint)
                        .frame(width: 38, height: 38)
                        .background(tint.opacity(0.14))
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))

                    VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                        Text(title)
                            .font(Theme.Typography.headline)
                            .foregroundColor(Theme.Colors.primaryText)
                            .lineLimit(1)
                        Text(subtitle)
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.backward")
                        .font(.system(size: Theme.Icon.sm, weight: .bold))
                        .foregroundColor(Theme.Colors.tertiaryText)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .buttonStyle(.plain)
    }
}

/// مُعدِّل دخول لطيف: البطاقة تنزل قليلًا + تتلاشى للداخل، مع تأخير متدرّج
/// حسب ترتيبها — يعطي إحساس إن الشاشة "تتفتّح" حيّة. `key` يعيد التشغيل عند
/// كل تحميل/تحديث.
private struct RevealModifier: ViewModifier {
    let order: Int
    let key: Int
    @State private var shown = false

    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : 14)
            .onAppear { animateIn() }
            .onChange(of: key) {
                // إعادة التشغيل عند تحديث اللقطة.
                shown = false
                animateIn()
            }
    }

    private func animateIn() {
        withAnimation(
            .spring(response: 0.5, dampingFraction: 0.85)
                .delay(Double(order) * 0.08)
        ) {
            shown = true
        }
    }
}

extension View {
    /// يطبّق دخولًا متدرّجًا حسب الترتيب, يُعاد تشغيله عند تغيّر `key`.
    func reveal(order: Int, key: Int) -> some View {
        modifier(RevealModifier(order: order, key: key))
    }
}

/// ورقة بسيطة لإعادة ترتيب عناصر الرئيسية بالجر: قائمة بوضع تحرير دائم وأيدي جر.
/// كل نقلة تُحفظ فورًا، والرئيسية تعكسها مباشرة لأنها تقرأ نفس `store.order`.
struct HomeReorderSheet: View {
    @ObservedObject var store: HomeStore
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                SandyBackground()
                List {
                    Section {
                        ForEach(store.order) { block in
                            HStack(spacing: Theme.Spacing.md) {
                                Image(systemName: block.icon)
                                    .foregroundColor(Theme.Colors.accent)
                                    .frame(width: 26)
                                Text(lang.s(block.titleKey))
                                    .font(Theme.Typography.body)
                                    .foregroundColor(Theme.Colors.primaryText)
                                Spacer(minLength: 0)
                            }
                            .listRowBackground(Color.clear)
                        }
                        .onMove { store.move(from: $0, to: $1) }
                    } header: {
                        Text(lang.s("home.reorderHint"))
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                            .textCase(nil)
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .environment(\.editMode, .constant(.active))
            }
            .navigationTitle(lang.s("home.reorderTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.s("common.done")) { dismiss() }
                }
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }
}
