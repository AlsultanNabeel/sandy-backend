import SwiftUI

/// نظام تصميم ساندي — مطابق لباليت الويب الداكن (frontend/index.css).
enum Theme {

    enum Colors {
        /// الأزرق الكهربائي — للعنصر المهيمن الواحد بكل شاشة فقط.
        static let accent = Color(red: 0.0, green: 0.831, blue: 1.0)         // #00D4FF
        static let accentSoft = Color(red: 0.373, green: 0.890, blue: 1.0)   // ~#5FE3FF
        static let accentDeep = Color(red: 0.0, green: 0.588, blue: 1.0)     // #0096FF
        /// سيان أهدأ لإشارات ثانوية محدودة حتى ما ينافس الأساسي.
        static let secondary = Color(red: 0.224, green: 0.776, blue: 0.886)  // ~#39C6E2

        static let spark = Color(red: 0.0, green: 0.831, blue: 1.0)          // #00D4FF

        static let background = Color(red: 0.008, green: 0.020, blue: 0.031) // #020508
        static let card = Color(red: 0.039, green: 0.078, blue: 0.133)      // ~#0A1422
        static let surface = Color(red: 0.055, green: 0.102, blue: 0.165)    // ~#0E1A2A

        static let primaryText = Color(red: 0.941, green: 0.980, blue: 1.0)  // #F0FAFF
        static let secondaryText = Color(red: 0.616, green: 0.698, blue: 0.776) // ~#9DB2C6
        static let tertiaryText = Color(red: 0.439, green: 0.514, blue: 0.592)  // ~#70838F
        static let onAccent = Color(red: 0.008, green: 0.071, blue: 0.110)   // ~#02121C

        static let border = Color(red: 0.0, green: 0.831, blue: 1.0).opacity(0.18)

        static let success = Color(red: 0.204, green: 0.878, blue: 0.690)    // ~#34E0B0
        /// كهرماني — يحلّ محل الأحمر الصارخ بالأخطاء.
        static let warn = Color(red: 1.0, green: 0.722, blue: 0.302)         // ~#FFB84D
        static let warnSoft = Color(red: 0.165, green: 0.118, blue: 0.047)   // ~#2A1E0C
        static let danger = Color(red: 1.0, green: 0.420, blue: 0.420)       // ~#FF6B6B
    }

    enum Typography {
        static let largeTitle = Font.system(size: 28, weight: .bold, design: .rounded)
        static let title = Font.system(size: 22, weight: .bold, design: .rounded)
        static let headline = Font.system(size: 17, weight: .semibold, design: .rounded)
        static let body = Font.system(size: 16, weight: .regular)
        static let callout = Font.system(size: 15, weight: .medium)
        static let subheadline = Font.system(size: 14, weight: .regular)
        static let caption = Font.system(size: 12, weight: .regular)
        static let button = Font.system(size: 16, weight: .semibold, design: .rounded)
    }

    enum Spacing {
        static let xs: CGFloat = 4
        static let sm: CGFloat = 8
        static let md: CGFloat = 14
        static let lg: CGFloat = 20
        static let xl: CGFloat = 28
        static let xxl: CGFloat = 40
        /// بين المجموعات الكبيرة بالشاشة.
        static let section: CGFloat = 24
    }

    /// لا تستعمل أرقامًا حرّة بالشاشات.
    enum Icon {
        static let sm: CGFloat = 15   // داخل الأزرار/التسميات
        static let md: CGFloat = 18   // أيقونات الصفوف/التولبار
        static let lg: CGFloat = 24   // أيقونات بارزة
        static let xl: CGFloat = 40   // الحالة الفاضية/التتويج
    }

    enum Radius {
        static let card: CGFloat = 16
        static let bubble: CGFloat = 18
        static let control: CGFloat = 12
        static let pill: CGFloat = 999
    }

    enum Shadow {
        static let cardColor = Color.black.opacity(0.45)
        static let cardRadius: CGFloat = 9
        static let cardY: CGFloat = 4

        static let liftColor = Color.black.opacity(0.6)
        static let liftRadius: CGFloat = 18
        static let liftY: CGFloat = 8

        /// للعنصر المهيمن الواحد بكل شاشة فقط.
        static let glowColor = Theme.Colors.accent.opacity(0.34)
        static let glowRadius: CGFloat = 14
    }
}

// MARK: - ليكويد جلاس

/// سطح مموّه + لمسة أزرق + حافة لمعان + ظل ناعم.
struct LiquidGlass: ViewModifier {
    var cornerRadius: CGFloat = Theme.Radius.card
    var tint: Double = 0.06
    var shine: Double = 0.24

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        content
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
            .overlay {
                shape.stroke(
                    LinearGradient(
                        colors: [Color.white.opacity(shine),
                                 Theme.Colors.accent.opacity(shine * 0.55),
                                 Color.white.opacity(shine * 0.1)],
                        startPoint: .topLeading, endPoint: .bottomTrailing),
                    lineWidth: 1)
            }
            .shadow(color: Theme.Shadow.cardColor,
                    radius: Theme.Shadow.cardRadius, x: 0, y: Theme.Shadow.cardY)
    }
}

extension View {
    func liquidGlass(cornerRadius: CGFloat = Theme.Radius.card,
                     tint: Double = 0.06, shine: Double = 0.24) -> some View {
        modifier(LiquidGlass(cornerRadius: cornerRadius, tint: tint, shine: shine))
    }

    /// للعنصر المهيمن الواحد بكل شاشة فقط.
    func sandyGlow(_ on: Bool = true) -> some View {
        shadow(color: on ? Theme.Shadow.glowColor : .clear,
               radius: on ? Theme.Shadow.glowRadius : 0)
    }

    /// ضغطة زنبركية؛ للعناصر القابلة للنقر فقط، مش القوائم (بيتعارض مع السحب).
    func liquidGlassPress() -> some View {
        buttonStyle(LiquidGlassButtonStyle())
    }
}

// MARK: - زر زجاجي تفاعلي

/// ينكمش ويسطع عند الضغط ويرتدّ بزنبرك عند الإفلات.
struct LiquidGlassButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.92 : 1.0)
            .brightness(configuration.isPressed ? 0.06 : 0)
            .animation(.spring(response: 0.32, dampingFraction: 0.55),
                       value: configuration.isPressed)
    }
}

// MARK: - خلفية ساندي

/// أوبسيديان مع توهّجين أزرقين حتى يبان عمق الزجاج.
struct SandyBackground: View {
    var body: some View {
        ZStack {
            Theme.Colors.background
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


/// مستوى أهمية البطاقة، لتراتب بصري واضح بكل شاشة.
enum CardEmphasis {
    /// العنصر المهيمن (واحد بالشاشة).
    case primary
    case secondary
    /// سطح مسطّح بلا مادة ولا توهّج.
    case info
}

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
    func sandyCard() -> some View { modifier(CardStyle(emphasis: .secondary)) }
    func sandyCard(_ emphasis: CardEmphasis) -> some View { modifier(CardStyle(emphasis: emphasis)) }
}

struct SectionHeader: View {
    let title: String
    var body: some View {
        Text(title)
            .font(Theme.Typography.headline)
            .foregroundColor(Theme.Colors.primaryText)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// شريط يبيّن إن البيانات تجريبية.
struct DemoBanner: View {
    @EnvironmentObject var lang: LanguageManager

    var body: some View {
        HStack(spacing: Theme.Spacing.sm) {
            Image(systemName: "info.circle.fill")
                .accessibilityHidden(true)
            Text(lang.s("common.demoData"))
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

