import SwiftUI

/// مقاس بطاقة وترتيبها، لكل صفحة على حدة.
///
/// المقاس `CardSize` — صغير أو وسط أو كبير — مش رقم حرّ. المحتوى بيتبنى لكل
/// مقاس، فما في معنى لمقاس ما إله تصميم.
@MainActor
final class BoardStore: ObservableObject {
    @Published private(set) var sizes: [String: CardSize] = [:]
    @Published private(set) var order: [String] = []
    @Published var editing = false

    private let key: String

    init(_ screen: String) {
        self.key = "board.\(screen)"
        load()
    }

    // ── قراءة ────────────────────────────────────────────────────────────────

    func size(_ id: String, default def: CardSize) -> CardSize {
        sizes[id] ?? def
    }

    /// البطاقات بترتيب المستخدم.
    ///
    /// أي بطاقة جديدة — أضفناها بتحديث — بتقعد بمكانها الطبيعي من الكود، مش
    /// بالآخر. بطاقة جديدة نازلة تحت آخر إشي رتّبته بتبيّن كأنها غلط.
    /// الرُّتَب مبنيّة بخطوة مستقلة، والمقارنة بتقرا منها وبس.
    ///
    /// كانت المقارنة سطر واحد فيه قاموسان و`map` وتحويل نوع ومعامِلا `??` —
    /// والمترجم وقف عاجز عن حلّه («unable to type-check in reasonable time»).
    /// المشكلة مش الحجم، المشكلة إنه كل جزء من التعبير إله أنواع محتملة متعددة،
    /// فالاحتمالات بتتضاعف. الأنواع الصريحة هون بتقطع الشجرة قبل ما تكبر.
    func arrange<T: BoardIdentifiable>(_ cards: [T]) -> [T] {
        guard !order.isEmpty else { return cards }

        var rank: [String: Double] = [:]
        for (i, id) in order.enumerated() {
            rank[id] = Double(i)
        }

        // البطاقة اللي ما إلها ترتيب محفوظ بتقعد جنب اللي قبلها بالكود، مش
        // بالآخر — بطاقة جديدة نازلة تحت آخر إشي رتّبته بتبيّن كأنها غلط.
        var last: Double = -1
        var run: Double = 0
        for card in cards {
            let id: String = card.boardID
            if let r = rank[id] {
                last = r
                run = 0
            } else {
                run += 1
                rank[id] = last + run / 1000
            }
        }

        return cards.sorted { (a: T, b: T) -> Bool in
            let ra: Double = rank[a.boardID] ?? 0
            let rb: Double = rank[b.boardID] ?? 0
            return ra < rb
        }
    }

    var isCustomised: Bool { !order.isEmpty || !sizes.isEmpty }

    // ── كتابة ────────────────────────────────────────────────────────────────

    /// المقاس بينحفظ لحظة ما يتغيّر.
    ///
    /// كان بينحفظ لما ترفع إيدك من إيماءة، وأي إيماءة بتنقطع كانت بتضيّع
    /// النتيجة. مقاس بينختار بزرّ ما إله «نهاية إيماءة» أصلًا، وبينحفظ فورًا.
    func setSize(_ v: CardSize, for id: String) {
        sizes[id] = v
        save()
    }

    func setOrder(_ ids: [String]) { order = ids; save() }

    /// ترتيب أثناء السحب — بلا حفظ.
    ///
    /// السحب بيعيد الترتيب عشرات المرّات بالثانية وإنت ماسك، وكتابة القرص مع
    /// كل وحدة بتخلّي الإصبع تتعتّر. الحفظ بيصير مرّة لما ترفع إيدك.
    func setOrderLive(_ ids: [String]) { order = ids }

    func reset() { sizes = [:]; order = []; save() }

    func save() {
        let d = UserDefaults.standard
        d.set(sizes.mapValues(\.rawValue), forKey: "\(key).sizes")
        d.set(order, forKey: "\(key).order")
    }

    private func load() {
        let d = UserDefaults.standard
        let raw: [String: String] =
            (d.dictionary(forKey: "\(key).sizes") as? [String: String]) ?? [:]
        sizes = raw.compactMapValues(CardSize.init(rawValue:))
        order = d.stringArray(forKey: "\(key).order") ?? []
    }
}

/// أي بطاقة إلها معرّف ثابت ينحفظ عليه حجمها وترتيبها.
///
/// المعرّف نص مكتوب بالإيد مش موقع بالمصفوفة: الموقع بيتزحلق أول ما حدا يضيف
/// بطاقة بالنص، وساعتها ترتيب كل مستخدم بيتغيّر لحاله — وبيبيّن كأن التطبيق نسي
/// ترتيبك، مش كأنه غلط برمجي.
protocol BoardIdentifiable {
    var boardID: String { get }
}
