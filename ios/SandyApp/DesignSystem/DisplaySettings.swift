import SwiftUI

/// «العرض» in Profile: text size and element size on top of the device's settings,
/// and light / dark / automatic. Saved on the device and applied at once: the theme's
/// spacing, radii and icon sizes read `elementScale`, so every view that uses them
/// redraws when it moves; text follows `textStep` through the Dynamic Type size.
@Observable
final class DisplaySettings {
    static let shared = DisplaySettings()

    enum Appearance: String, CaseIterable {
        case system, light, dark

        var scheme: ColorScheme? {
            switch self {
            case .system: return nil
            case .light: return .light
            case .dark: return .dark
            }
        }
    }

    /// Steps of the device's text size, up or down (−2 … +4).
    var textStep: Int { didSet { save() } }
    /// Buttons, cards and gaps: 0.85 … 1.3 of the design.
    var elementScale: Double { didSet { save() } }
    var appearance: Appearance { didSet { save() } }

    static let textSteps = -2...4
    static let elementRange = 0.85...1.3

    private init() {
        let d = UserDefaults.standard
        textStep = d.object(forKey: "display.textStep") as? Int ?? 0
        elementScale = d.object(forKey: "display.elementScale") as? Double ?? 1
        appearance = Appearance(rawValue: d.string(forKey: "display.appearance") ?? "") ?? .system
    }

    private func save() {
        let d = UserDefaults.standard
        d.set(textStep, forKey: "display.textStep")
        d.set(elementScale, forKey: "display.elementScale")
        d.set(appearance.rawValue, forKey: "display.appearance")
    }

    /// The device's text size moved by `textStep`, kept at sizes the layouts were built for.
    func textSize(from device: DynamicTypeSize) -> DynamicTypeSize {
        let all = DynamicTypeSize.allCases
        let maxIndex = all.firstIndex(of: .accessibility3) ?? all.count - 1
        let start = all.firstIndex(of: device) ?? all.firstIndex(of: .large) ?? 3
        return all[min(max(start + textStep, 0), maxIndex)]
    }
}

/// Applies the display settings to everything under it (the app's root).
struct DisplayEnvironment: ViewModifier {
    @Environment(\.dynamicTypeSize) private var deviceSize
    private var display = DisplaySettings.shared

    func body(content: Content) -> some View {
        content
            .dynamicTypeSize(display.textSize(from: deviceSize))
            .preferredColorScheme(display.appearance.scheme)
    }
}

extension View {
    func sandyDisplay() -> some View { modifier(DisplayEnvironment()) }
}

/// A fixed design size as a font that grows with the reader's text size: the size is
/// scaled for the current Dynamic Type size (the device's, moved by the app's own step).
private struct ScaledFont: ViewModifier {
    @Environment(\.dynamicTypeSize) private var size
    let points: CGFloat
    let weight: Font.Weight
    let design: Font.Design
    let style: UIFont.TextStyle

    func body(content: Content) -> some View {
        let traits = UITraitCollection(preferredContentSizeCategory: UIContentSizeCategory(size))
        let scaled = UIFontMetrics(forTextStyle: style).scaledValue(for: points, compatibleWith: traits)
        content.font(.system(size: scaled, weight: weight, design: design))
    }
}

extension View {
    /// `.font(.system(size:))` that follows the text size setting.
    func scaledFont(_ points: CGFloat, weight: Font.Weight = .regular, design: Font.Design = .default,
                    relativeTo style: UIFont.TextStyle = .body) -> some View {
        modifier(ScaledFont(points: points, weight: weight, design: design, style: style))
    }
}

// MARK: - تقليل الحركة

extension Animation {
    /// Nothing moves when the device asks for reduced motion; the change still happens.
    var reduced: Animation? {
        UIAccessibility.isReduceMotionEnabled ? nil : self
    }
}
