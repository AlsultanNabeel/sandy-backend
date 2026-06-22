import SwiftUI

/// نظام تصميم ساندي — مطابق لباليت الويب الداكن (frontend/index.css):
/// أوبسيديان قريب من الأسود + أزرق كهربائي. نخليه مركزي: كل الواجهات تسحب منه.
///
/// من وين جت الألوان (hex من index.css):
///   - الخلفية   `#020508` (body background)                  → خلفية الشاشة
///   - النص الفاتح `#F0FAFF` (body color)                      → النص الأساسي
///   - الأزرق الكهربائي `#00D4FF` → `#0096FF` → `#00D4FF` (elec gradient/glow) → اللمسات
///   - الأسطح    `rgba(0,8,18,.65)` / `rgba(0,12,24,.55)`      → تقريب معتم داكن
enum Theme {

    // ── الألوان ─────────────────────────────────────────────────────────
    enum Colors {
        /// اللمسة الأساسية: الأزرق الكهربائي (#00D4FF).
        static let accent = Color(red: 0.0, green: 0.831, blue: 1.0)         // #00D4FF
        /// تدرّج أفتح من الأساسي (لأزرار/توهج) — سماوي فاتح.
        static let accentSoft = Color(red: 0.373, green: 0.890, blue: 1.0)   // ~#5FE3FF
        /// نسخة أعمق من الأساسي (#0096FF) — حدود/نهاية التدرّج.
        static let accentDeep = Color(red: 0.0, green: 0.588, blue: 1.0)     // #0096FF

        /// لمسة "ساندي" الكهربائية (#00D4FF) — نفس الأكسنت، استعمال محدود.
        static let spark = Color(red: 0.0, green: 0.831, blue: 1.0)          // #00D4FF

        /// خلفية الشاشة (أوبسيديان قريب من الأسود مع لمحة أزرق).
        static let background = Color(red: 0.008, green: 0.020, blue: 0.031) // #020508
        /// خلفية البطاقات/الأسطح (تقريب معتم لـ rgba(0,12,24,.55)).
        static let card = Color(red: 0.039, green: 0.078, blue: 0.133)      // ~#0A1422
        /// سطح ثانوي (حقول، شرائح) أغمق قليلاً.
        static let surface = Color(red: 0.055, green: 0.102, blue: 0.165)    // ~#0E1A2A

        /// فقاعة المستخدم بالشات — أكسنت أزرق بشفافية.
        static let userBubble = Color(red: 0.0, green: 0.831, blue: 1.0).opacity(0.18)
        /// فقاعة ساندي بالشات — سطح داكن.
        static let sandyBubble = Color(red: 0.055, green: 0.102, blue: 0.165) // ~#0E1A2A

        /// النص الأساسي (#F0FAFF) — صريح عشان يبقى فاتح على الخلفية الداكنة.
        static let primaryText = Color(red: 0.941, green: 0.980, blue: 1.0)  // #F0FAFF
        /// النص الثانوي (~#8AA0B5) — رمادي-أزرق مكتوم.
        static let secondaryText = Color(red: 0.541, green: 0.627, blue: 0.710) // ~#8AA0B5
        /// نص فوق التعبئة الكهربائية (الأزرق الساطع) — داكن قريب من الأسود.
        static let onAccent = Color(red: 0.008, green: 0.071, blue: 0.110)   // ~#02121C

        /// حدّ كهربائي خفيف (يقابل rgba(0,212,255,0.18) بالويب).
        static let border = Color(red: 0.0, green: 0.831, blue: 1.0).opacity(0.18)

        // حالات — مقروءة على الخلفية الداكنة
        static let success = Color(red: 0.204, green: 0.878, blue: 0.690)    // ~#34E0B0
        /// تنبيه ودّي (كهرماني) — يحلّ محل الأحمر الصارخ بالأخطاء.
        static let warn = Color(red: 1.0, green: 0.722, blue: 0.302)         // ~#FFB84D
        /// خلفية فقاعة التنبيه الودّي (كهرماني داكن).
        static let warnSoft = Color(red: 0.165, green: 0.118, blue: 0.047)   // ~#2A1E0C
        /// أحمر هادئ للحذف (نفس أحمر الويب #ff6b6b).
        static let danger = Color(red: 1.0, green: 0.420, blue: 0.420)       // ~#FF6B6B
    }

    // ── الخطوط ──────────────────────────────────────────────────────────
    /// أحجام/أوزان موحّدة (نعتمد على خط النظام — يدعم العربية ممتاز).
    enum Typography {
        static let largeTitle = Font.system(size: 28, weight: .bold, design: .rounded)
        static let title = Font.system(size: 22, weight: .bold, design: .rounded)
        static let headline = Font.system(size: 17, weight: .semibold, design: .rounded)
        static let body = Font.system(size: 16, weight: .regular)
        static let callout = Font.system(size: 15, weight: .medium)
        static let subheadline = Font.system(size: 14, weight: .regular)
        static let caption = Font.system(size: 12, weight: .regular)
        /// نص الأزرار.
        static let button = Font.system(size: 16, weight: .semibold, design: .rounded)
    }

    // ── المسافات ────────────────────────────────────────────────────────
    enum Spacing {
        static let xs: CGFloat = 4
        static let sm: CGFloat = 8
        static let md: CGFloat = 14
        static let lg: CGFloat = 20
        static let xl: CGFloat = 28
        static let xxl: CGFloat = 40
    }

    // ── الحواف ──────────────────────────────────────────────────────────
    enum Radius {
        static let card: CGFloat = 16
        static let bubble: CGFloat = 18
        static let control: CGFloat = 12
        static let pill: CGFloat = 999
    }

    // ── الظلال ──────────────────────────────────────────────────────────
    /// ظلال داكنة خفيفة تقابل box-shadow الويب (مثلاً 0 8px 26px -8px rgba(0,0,0,0.7)).
    enum Shadow {
        /// ظل البطاقة العادي — أسود خفيف على الخلفية الداكنة.
        static let cardColor = Color.black.opacity(0.45)
        static let cardRadius: CGFloat = 8
        static let cardY: CGFloat = 3

        /// ظل مرفوع (عناصر عائمة كزر الإضافة / ساندي العائمة).
        static let liftColor = Color.black.opacity(0.6)
        static let liftRadius: CGFloat = 18
        static let liftY: CGFloat = 8

        /// توهج أزرق كهربائي حول العناصر المميزة (يقابل blue glow بالويب).
        static let glowColor = Theme.Colors.accent.opacity(0.55)
        static let glowRadius: CGFloat = 18
    }
}

// MARK: - ليكويد جلاس (زجاج آبل الجديد، بأزرقنا)

/// معدِّن «الزجاج السائل»: سطح مموّه (`ultraThinMaterial`) + لمسة أزرق خفيفة +
/// حافة لمعان (فاتحة فوق، تخفت تحت) + ظل ناعم. يعطي إحساس زجاج آبل الجديد لكن
/// بهويتنا الكهربائية. متوافق iOS 16 (الـ Material متاح من iOS 15).
struct LiquidGlass: ViewModifier {
    var cornerRadius: CGFloat = Theme.Radius.card
    /// قوة لمسة الأزرق فوق الزجاج (0 = زجاج صافٍ).
    var tint: Double = 0.10

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        content
            // الزجاج نفسه + تلوين أزرق خفيف خلف المحتوى.
            .background {
                ZStack {
                    shape.fill(.ultraThinMaterial)
                    shape.fill(
                        LinearGradient(
                            colors: [Theme.Colors.accent.opacity(tint),
                                     Theme.Colors.accent.opacity(tint * 0.2)],
                            startPoint: .topLeading, endPoint: .bottomTrailing))
                }
            }
            .clipShape(shape)
            // حافة اللمعان — السمة المميزة للزجاج السائل.
            .overlay {
                shape.stroke(
                    LinearGradient(
                        colors: [Color.white.opacity(0.40),
                                 Theme.Colors.accent.opacity(0.22),
                                 Color.white.opacity(0.04)],
                        startPoint: .topLeading, endPoint: .bottomTrailing),
                    lineWidth: 1)
            }
            .shadow(color: Theme.Shadow.cardColor, radius: 12, x: 0, y: 5)
    }
}

extension View {
    /// يكسي أي عرض بزجاج ساندي السائل (نفس الزرقة).
    func liquidGlass(cornerRadius: CGFloat = Theme.Radius.card, tint: Double = 0.10) -> some View {
        modifier(LiquidGlass(cornerRadius: cornerRadius, tint: tint))
    }
}

// MARK: - خلفية ساندي (أوبسيديان + توهّجات يكسرها الزجاج)

/// خلفية الشاشة: أوبسيديان غامق مع توهّجين أزرقين ناعمين — يعطيان الزجاج شيء
/// ينكسر فيه فيبان عمقه. تُستعمل بكل الشاشات بدل لون مصمت.
struct SandyBackground: View {
    var body: some View {
        ZStack {
            Theme.Colors.background
            RadialGradient(
                colors: [Theme.Colors.accent.opacity(0.16), .clear],
                center: .topLeading, startRadius: 0, endRadius: 420)
            RadialGradient(
                colors: [Theme.Colors.accentDeep.opacity(0.13), .clear],
                center: .bottomTrailing, startRadius: 0, endRadius: 460)
        }
        .ignoresSafeArea()
    }
}

// MARK: - أنماط قابلة لإعادة الاستخدام

/// نمط بطاقة ساندي — صار زجاج سائل (مموّه + لمعان أزرق).
struct CardStyle: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(Theme.Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlass(cornerRadius: Theme.Radius.card)
    }
}

extension View {
    /// يحوّل أي عرض لبطاقة بنمط ساندي (زجاج سائل).
    func sandyCard() -> some View { modifier(CardStyle()) }
}

/// عنوان قسم صغير (لاستعماله أعلى القوائم).
struct SectionHeader: View {
    let title: String
    var body: some View {
        Text(title)
            .font(Theme.Typography.headline)
            .foregroundColor(Theme.Colors.primaryText)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// شريط صغير غير مزعج يبيّن إن البيانات تجريبية (للزائر/غير المالك).
struct DemoBanner: View {
    var body: some View {
        HStack(spacing: Theme.Spacing.sm) {
            Image(systemName: "info.circle.fill")
            Text("بيانات تجربة")
                .font(.caption).bold()
            Spacer(minLength: 0)
        }
        .foregroundColor(Theme.Colors.accent)
        .padding(.vertical, Theme.Spacing.sm)
        .padding(.horizontal, Theme.Spacing.md)
        .background(Theme.Colors.accent.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, Theme.Spacing.sm)
    }
}

/// حالة فاضية لطيفة (لما القائمة فاضية).
struct EmptyStateView: View {
    let icon: String
    let message: String
    var body: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: icon)
                .font(.system(size: 40))
                .foregroundColor(Theme.Colors.secondaryText)
            Text(message)
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Spacing.xl)
    }
}
