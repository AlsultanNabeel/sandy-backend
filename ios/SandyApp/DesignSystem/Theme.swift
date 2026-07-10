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
        /// اللمسة الأساسية (Primary): الأزرق الكهربائي (#00D4FF) — تُستعمل للعنصر
        /// المهيمن الواحد بكل شاشة فقط (سي تي أيه/بطاقة أساسية)، مش لكل إشي.
        static let accent = Color(red: 0.0, green: 0.831, blue: 1.0)         // #00D4FF
        /// تدرّج أفتح من الأساسي (لأزرار/توهج) — سماوي فاتح.
        static let accentSoft = Color(red: 0.373, green: 0.890, blue: 1.0)   // ~#5FE3FF
        /// نسخة أعمق من الأساسي (#0096FF) — حدود/نهاية التدرّج.
        static let accentDeep = Color(red: 0.0, green: 0.588, blue: 1.0)     // #0096FF
        /// اللمسة الثانوية (Secondary): سماوي/سيان أهدأ — لإشارات ثانوية محدودة
        /// (أيقونات أقسام، شارات) حتى ما ينافس الأزرق الأساسي. استعمال مقتصد.
        static let secondary = Color(red: 0.224, green: 0.776, blue: 0.886)  // ~#39C6E2

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
        /// النص الثانوي (~#9DB2C6) — رمادي-أزرق، رُفع تبايُنه شوي لقراءة أوضح.
        static let secondaryText = Color(red: 0.616, green: 0.698, blue: 0.776) // ~#9DB2C6
        /// النص الثالثي (الأقل أهمية) — تسميات/تلميحات خافتة بتراتب أدنى.
        static let tertiaryText = Color(red: 0.439, green: 0.514, blue: 0.592)  // ~#70838F
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
        /// مسافة التنفّس بين أقسام الشاشة (white space) — استعملها بين المجموعات
        /// الكبيرة حتى يصير اللي‌أوت أقل ضغطًا.
        static let section: CGFloat = 24
    }

    // ── أحجام الأيقونات ───────────────────────────────────────────────────
    /// مقياس موحّد لأحجام الأيقونات (نقطة) — لا تستعمل أرقامًا حرّة بالشاشات.
    enum Icon {
        static let sm: CGFloat = 15   // داخل الأزرار/التسميات
        static let md: CGFloat = 18   // أيقونات الصفوف/التولبار
        static let lg: CGFloat = 24   // أيقونات بارزة
        static let xl: CGFloat = 40   // الحالة الفاضية/التتويج
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

        /// توهج أزرق كهربائي حول العنصر المميّز الواحد — مخفّف ~٣٨٪ لتقليل الضجيج
        /// البصري (كان ٠٫٥٥). يُستعمل بحذر: للعنصر المهيمن بكل شاشة فقط.
        static let glowColor = Theme.Colors.accent.opacity(0.34)
        static let glowRadius: CGFloat = 14
    }
}

// MARK: - ليكويد جلاس (زجاج آبل الجديد، بأزرقنا)

/// معدِّن «الزجاج السائل»: سطح مموّه (`ultraThinMaterial`) + لمسة أزرق خفيفة +
/// حافة لمعان (فاتحة فوق، تخفت تحت) + ظل ناعم. يعطي إحساس زجاج آبل الجديد لكن
/// بهويتنا الكهربائية. متوافق iOS 16 (الـ Material متاح من iOS 15).
struct LiquidGlass: ViewModifier {
    var cornerRadius: CGFloat = Theme.Radius.card
    /// قوة لمسة الأزرق فوق الزجاج (0 = زجاج صافٍ). خُفّضت الافتراضية لتقليل الضجيج.
    var tint: Double = 0.06
    /// قوة لمعان الحافة (0 = بلا لمعان). خُفّضت ~٤٠٪ حتى ما تتنافس كل البطاقات.
    var shine: Double = 0.24

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
            // حافة اللمعان — مخفّفة لتقليل الضجيج (السمة باقية بس أهدأ).
            .overlay {
                shape.stroke(
                    LinearGradient(
                        colors: [Color.white.opacity(shine),
                                 Theme.Colors.accent.opacity(shine * 0.55),
                                 Color.white.opacity(shine * 0.1)],
                        startPoint: .topLeading, endPoint: .bottomTrailing),
                    lineWidth: 1)
            }
            // ظل أنعم وأقرب (كان radius 12/y 5) — عمق أهدأ بضجيج أقل.
            .shadow(color: Theme.Shadow.cardColor, radius: 9, x: 0, y: 4)
    }
}

extension View {
    /// يكسي أي عرض بزجاج ساندي السائل (نفس الزرقة).
    func liquidGlass(cornerRadius: CGFloat = Theme.Radius.card,
                     tint: Double = 0.06, shine: Double = 0.24) -> some View {
        modifier(LiquidGlass(cornerRadius: cornerRadius, tint: tint, shine: shine))
    }

    /// توهّج ساندي الموحّد — استعمله للعنصر المهيمن الواحد بكل شاشة فقط (مش لكل
    /// بطاقة). مخفّف مركزيًّا عبر `Theme.Shadow.glow*`.
    func sandyGlow(_ on: Bool = true) -> some View {
        shadow(color: on ? Theme.Shadow.glowColor : .clear,
               radius: on ? Theme.Shadow.glowRadius : 0)
    }

    /// إحساس آبل التفاعلي بلا أدوات iOS 26: الزجاج "يغوص" بنعومة عند اللمس
    /// ويرتدّ بنبضة زنبركية مرنة كأنه قطرة ماء. للعناصر القابلة للنقر فقط (مو
    /// القوائم القابلة للتمرير حتى ما يتعارض مع السحب).
    func liquidGlassPress() -> some View {
        buttonStyle(LiquidGlassButtonStyle())
    }
}

// MARK: - زر زجاجي تفاعلي (تقليد الزجاج السائل التفاعلي بلا iOS 26)

/// نمط زر يقلّد الزجاج السائل التفاعلي تاع آبل: عند الضغط ينكمش بنعومة ويسطع
/// خفيف، وعند الإفلات يرتدّ بزنبرك مرن (تخميد منخفض) فتحسّه "يهتز كقطرة ماء".
/// متوافق iOS 16 — مبني على ButtonStyle القياسي فقط.
struct LiquidGlassButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.92 : 1.0)
            .brightness(configuration.isPressed ? 0.06 : 0)
            .animation(.spring(response: 0.32, dampingFraction: 0.55),
                       value: configuration.isPressed)
    }
}

// MARK: - خلفية ساندي (أوبسيديان + توهّجات يكسرها الزجاج)

/// خلفية الشاشة: أوبسيديان غامق مع توهّجين أزرقين ناعمين — يعطيان الزجاج شيء
/// ينكسر فيه فيبان عمقه. تُستعمل بكل الشاشات بدل لون مصمت.
struct SandyBackground: View {
    var body: some View {
        ZStack {
            Theme.Colors.background
            // توهّجان خلفيّان مخفّفان (كانا ٠٫١٦ و٠٫١٣) — عمق أهدأ، ضجيج أقل.
            RadialGradient(
                colors: [Theme.Colors.accent.opacity(0.10), .clear],
                center: .topLeading, startRadius: 0, endRadius: 440)
            RadialGradient(
                colors: [Theme.Colors.accentDeep.opacity(0.08), .clear],
                center: .bottomTrailing, startRadius: 0, endRadius: 480)
        }
        .ignoresSafeArea()
    }
}

// MARK: - أنماط قابلة لإعادة الاستخدام

/// مستوى أهمية البطاقة — يقود وزنها البصري حتى يصير تراتب واضح بكل شاشة:
/// عنصر أساسي واحد بارز، وبقية البطاقات أخفّ تدريجيًّا.
enum CardEmphasis {
    /// العنصر المهيمن (واحد بالشاشة): زجاج + حدّ أوضح + توهّج خفيف موحّد.
    case primary
    /// الافتراضي: زجاج هادئ بلا توهّج.
    case secondary
    /// الأخفّ (معلومة/ثانوي جدًّا): سطح مسطّح خفيف بلا مادة ولا توهّج — أقل ضجيج.
    case info
}

/// نمط بطاقة ساندي — زجاج سائل بوزن بصري حسب الأهمية.
struct CardStyle: ViewModifier {
    var emphasis: CardEmphasis = .secondary

    @ViewBuilder
    func body(content: Content) -> some View {
        let base = content
            .padding(Theme.Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
        let shape = RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)

        switch emphasis {
        case .primary:
            base
                .liquidGlass(cornerRadius: Theme.Radius.card, tint: 0.10, shine: 0.30)
                .overlay(shape.stroke(Theme.Colors.accent.opacity(0.28), lineWidth: 1))
                .sandyGlow()
        case .secondary:
            base
                .liquidGlass(cornerRadius: Theme.Radius.card)
        case .info:
            base
                .background(shape.fill(Theme.Colors.surface.opacity(0.45)))
                .overlay(shape.stroke(Color.white.opacity(0.05), lineWidth: 1))
        }
    }
}

extension View {
    /// بطاقة ساندي بالوزن الافتراضي (ثانوي) — متوافقة مع كل الاستعمالات الحالية.
    func sandyCard() -> some View { modifier(CardStyle(emphasis: .secondary)) }
    /// بطاقة بوزن بصري صريح (أساسي/ثانوي/معلومة) — لبناء التراتب.
    func sandyCard(_ emphasis: CardEmphasis) -> some View { modifier(CardStyle(emphasis: emphasis)) }
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
