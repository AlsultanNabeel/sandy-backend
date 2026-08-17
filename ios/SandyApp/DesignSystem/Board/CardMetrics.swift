import SwiftUI

/// مقاسات البطاقة — نفس منطق ودجات الآيفون.
///
/// **ثلاثة مقاسات، مش سلّم مفتوح.**
///
/// النسخة اللي قبل كانت بتخلّيك تصغّر لحدّ ثُمن الشاشة. النتيجة بطاقة ما بتقول
/// إشي ومفتاح أصغر من إصبعك — حرّية بتوصّل لمكان ما إله معنى. أبل بتعطي ثلاثة
/// وبس، والسبب إنه كل واحد فيهن إله تصميم مكتوب، وأي مقاس برّاهن ما إله.
///
/// وأصغر واحد **نص السطر مربّع** — وهاد بالضبط الودجة الصغيرة بالآيفون، وأول
/// مقاس بتقعد فيه بطاقتان جنب بعض.
enum CardSize: String, CaseIterable, Codable {
    /// نص السطر، مربّع. تنتين بيتشاركوا السطر.
    case small
    /// السطر كامل، وارتفاعه ع قد محتواه.
    case medium
    /// السطر كامل، ومساحة تتنفّس فيها.
    case large

    /// نسبة العرض من عرض اللوح.
    var fraction: Double {
        switch self {
        case .small:  return 0.5
        case .medium: return 1.0
        case .large:  return 1.0
        }
    }

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

/// كم مساحة أعطاها المالك لهاي البطاقة — عشان محتواها يقرّر شكله.
///
/// **هاد الفرق بين تصغير وتكييف.**
///
/// النسخة اللي قبل كانت بتصغّر البطاقة زي صورة: كل إشي جواها بينزل بنفس النسبة،
/// فالنص بيصير غير مقروء والمفتاح بيصير أصغر من إصبعك. المالك وصف اللي بده ياه
/// بدقّة: بطاقة فيها مفتاح، لما تصغر، بتصير **مفتاح واسمه فوقه، وبخط كبير**.
/// يعني تصميم تاني، مش نفس التصميم مصغّر.
///
/// فبدل ما نكبّس المحتوى، منقول للمحتوى قدّيش عنده مساحة وبيقرّر هو. زي ودجات
/// الآيفون بالضبط: الصغيرة والكبيرة تصميمان، مش مقياسان.
struct CardMetrics: Equatable {
    let size: CardSize
    /// عرض البطاقة بالنقاط.
    let width: CGFloat

    /// ضيّقة: ما بتسع صفًّا أفقيًا فيه أيقونة وعنوان ووصف وتحكّم.
    var isCompact: Bool { size == .small }
}

private struct CardMetricsKey: EnvironmentKey {
    /// الافتراضي «عرض كامل»: أي واجهة برّا اللوح بتشتغل بشكلها الطبيعي بلا ما
    /// تعرف إنه اللوح موجود أصلًا.
    static let defaultValue = CardMetrics(size: .medium,
                                          width: UIScreen.main.bounds.width)
}

extension EnvironmentValues {
    var cardMetrics: CardMetrics {
        get { self[CardMetricsKey.self] }
        set { self[CardMetricsKey.self] = newValue }
    }
}
