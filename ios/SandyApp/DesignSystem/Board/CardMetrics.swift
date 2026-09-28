import SwiftUI

/// ثلاثة مقاسات زي ودجات الآيفون، كل واحد إله تصميم؛ أصغرهم نص السطر مربّع.
enum CardSize: String, CaseIterable, Codable {
    /// نص السطر، مربّع. تنتين بيتشاركوا السطر.
    case small
    case medium
    case large

    var labelKey: String { "board.size.\(rawValue)" }

    func next() -> CardSize {
        switch self {
        case .small:  return .medium
        case .medium: return .large
        case .large:  return .small
        }
    }

    func previous() -> CardSize {
        switch self {
        case .small:  return .large
        case .medium: return .small
        case .large:  return .medium
        }
    }
}

/// المساحة المعطاة للبطاقة، حتى محتواها يقرّر شكله بدل ما ينصغّر كصورة.
struct CardMetrics: Equatable {
    let size: CardSize
    let width: CGFloat

    /// ما بتسع صفًّا أفقيًا فيه أيقونة وعنوان ووصف وتحكّم.
    var isCompact: Bool { size == .small }
}

private struct CardMetricsKey: EnvironmentKey {
    /// الافتراضي «عرض كامل» حتى أي واجهة برّا اللوح تشتغل بشكلها الطبيعي.
    static let defaultValue = CardMetrics(size: .medium,
                                          width: UIScreen.main.bounds.width)
}

extension EnvironmentValues {
    var cardMetrics: CardMetrics {
        get { self[CardMetricsKey.self] }
        set { self[CardMetricsKey.self] = newValue }
    }
}
