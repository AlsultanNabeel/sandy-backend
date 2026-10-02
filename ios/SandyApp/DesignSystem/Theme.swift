import SwiftUI

/// نظام تصميم ساندي — الغامق مطابق لباليت الويب (frontend/index.css)، والفاتح مبني
/// عليه بتباين مقروء على الأبيض.
enum Theme {

    enum Colors {
        /// Electric blue — the one dominant element on each screen. Darker in light mode so
        /// it still reads as text on white.
        static let accent = Color(light: 0x0077B6, dark: 0x00D4FF)
        static let accentSoft = Color(light: 0x2E9BD6, dark: 0x5FE3FF)
        static let accentDeep = Color(light: 0x005B8F, dark: 0x0096FF)
        /// A quieter cyan for a few secondary signals, so it never competes with the accent.
        static let secondary = Color(light: 0x16869E, dark: 0x39C6E2)

        static let spark = accent

        static let background = Color(light: 0xF4F7FB, dark: 0x020508)
        static let card = Color(light: 0xFFFFFF, dark: 0x0A1422)
        static let surface = Color(light: 0xE6EDF4, dark: 0x0E1A2A)

        static let primaryText = Color(light: 0x0B1A26, dark: 0xF0FAFF)
        static let secondaryText = Color(light: 0x45586A, dark: 0x9DB2C6)
        static let tertiaryText = Color(light: 0x627485, dark: 0x70838F)
        static let onAccent = Color(light: 0xFFFFFF, dark: 0x02121C)

        static let border = accent.opacity(0.18)

        static let success = Color(light: 0x0B8F6A, dark: 0x34E0B0)
        /// Amber — stands in for a harsh red on errors.
        static let warn = Color(light: 0xA65F00, dark: 0xFFB84D)
        static let warnSoft = Color(light: 0xFFF0D9, dark: 0x2A1E0C)
        static let danger = Color(light: 0xC62F2F, dark: 0xFF6B6B)

        /// The light catching a glass edge: white on dark, a faint blue-grey on light.
        static let shine = Color(light: 0xFFFFFF, dark: 0xFFFFFF)
        static let hairline = Color(light: 0x0B1A26, lightAlpha: 0.08, dark: 0xFFFFFF, darkAlpha: 0.05)
        /// Text and icons on a coloured fill (call bar, red button).
        static let onFill = Color.white
    }

    /// Text styles, so every token follows the device's text size (and the app's own step).
    enum Typography {
        static let largeTitle = Font.system(.title, design: .rounded, weight: .bold)
        static let title = Font.system(.title2, design: .rounded, weight: .bold)
        static let headline = Font.system(.headline, design: .rounded, weight: .semibold)
        static let body = Font.system(.callout)
        static let callout = Font.system(.subheadline, weight: .medium)
        static let subheadline = Font.system(.subheadline)
        static let caption = Font.system(.caption)
        static let button = Font.system(.callout, design: .rounded, weight: .semibold)
    }

    enum Spacing {
        private static var k: CGFloat { DisplaySettings.shared.elementScale }
        static var xs: CGFloat { 4 * k }
        static var sm: CGFloat { 8 * k }
        static var md: CGFloat { 14 * k }
        static var lg: CGFloat { 20 * k }
        static var xl: CGFloat { 28 * k }
        static var xxl: CGFloat { 40 * k }
        /// بين المجموعات الكبيرة بالشاشة.
        static var section: CGFloat { 24 * k }
    }

    /// لا تستعمل أرقامًا حرّة بالشاشات.
    enum Icon {
        private static var k: CGFloat { DisplaySettings.shared.elementScale }
        static var sm: CGFloat { 15 * k }   // داخل الأزرار/التسميات
        static var md: CGFloat { 18 * k }   // أيقونات الصفوف/التولبار
        static var lg: CGFloat { 24 * k }   // أيقونات بارزة
        static var xl: CGFloat { 40 * k }   // الحالة الفاضية/التتويج
    }

    enum Radius {
        static var card: CGFloat { 16 * DisplaySettings.shared.elementScale }
        static var bubble: CGFloat { 18 * DisplaySettings.shared.elementScale }
        static var control: CGFloat { 12 * DisplaySettings.shared.elementScale }
        static let pill: CGFloat = 999
    }

    enum Shadow {
        static let cardColor = Color(light: 0x0B1A26, lightAlpha: 0.10, dark: 0x000000, darkAlpha: 0.45)
        static let cardRadius: CGFloat = 9
        static let cardY: CGFloat = 4

        static let liftColor = Color(light: 0x0B1A26, lightAlpha: 0.16, dark: 0x000000, darkAlpha: 0.6)
        static let liftRadius: CGFloat = 18
        static let liftY: CGFloat = 8

        /// للعنصر المهيمن الواحد بكل شاشة فقط.
        static let glowColor = Theme.Colors.accent.opacity(0.30)
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
                        colors: [Theme.Colors.shine.opacity(shine),
                                 Theme.Colors.accent.opacity(shine * 0.55),
                                 Theme.Colors.shine.opacity(shine * 0.1)],
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
            .animation(Animation.spring(response: 0.32, dampingFraction: 0.55).reduced,
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
                .overlay(shape.stroke(Theme.Colors.hairline, lineWidth: 1))
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
            .accessibilityAddTraits(.isHeader)
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


// MARK: - ألوان بوضعين

extension Color {
    /// One colour per appearance, from hex (0xRRGGBB).
    init(light: UInt32, lightAlpha: Double = 1, dark: UInt32, darkAlpha: Double = 1) {
        self.init(UIColor { traits in
            traits.userInterfaceStyle == .light
                ? UIColor(hex: light, alpha: lightAlpha)
                : UIColor(hex: dark, alpha: darkAlpha)
        })
    }
}

extension UIColor {
    convenience init(hex: UInt32, alpha: Double = 1) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
    }
}
