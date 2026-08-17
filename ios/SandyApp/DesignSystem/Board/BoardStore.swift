import SwiftUI

/// حجم بطاقة وترتيبها، لكل صفحة على حدة.
///
/// **الحجم رقم واحد مش رقمين.** البطاقة بتنرسم مرّة بعرض اللوح، وبعدين بتنصغّر
/// بمعامل واحد — فالعرض والطول بينزلوا سوا وبتضل النِّسَب صح. تصغير العرض لحاله
/// كان بيخلّي النصوص تنكسر لسطور وترتفع البطاقة وهي بتصغر، وهاد اللي بيبيّن
/// «مركوب» ع الشاشة.
///
/// وكونه معامل واحد هو سبب السلاسة كمان: التغيير بيصير تحويلًا رسوميًا خالصًا،
/// بلا ما SwiftUI تعيد ترتيب أي إشي جوّا البطاقة. بتقدر تسحب الزاوية والمحتوى
/// كله بيتحرّك بستّين إطار بالثانية، لأنه ما في شغل غير الرسم.
///
/// **والمعامل نسبة مش نقاط.** الآيفون والآيباد بعرضين مختلفين، والدوران بيغيّر
/// العرض؛ نسبة من عرض اللوح بتضل صح بالحالتين، والنقاط بتضبط ع جهاز وبتخرب ع
/// التاني.
@MainActor
final class BoardStore: ObservableObject {
    /// أصغر وأكبر مقاس. الأصغر ثُمن العرض — أصغر من هيك بتصير البطاقة نقطة
    /// ملوّنة ما بتقول إشي، وحرّية بتوصّل لنتيجة ما إلها معنى مش حرّية.
    static let minScale = 0.125
    static let maxScale = 1.0

    @Published private(set) var scales: [String: Double] = [:]
    @Published private(set) var order: [String] = []
    @Published var editing = false

    private let key: String

    init(_ screen: String) {
        self.key = "board.\(screen)"
        load()
    }

    // ── قراءة ────────────────────────────────────────────────────────────────

    func scale(_ id: String, default def: Double) -> Double {
        scales[id] ?? def
    }

    /// البطاقات بترتيب المستخدم.
    ///
    /// أي بطاقة جديدة — أضفناها بتحديث — بتقعد بمكانها الطبيعي من الكود، مش
    /// بالآخر. بطاقة جديدة نازلة تحت آخر إشي رتّبته بتبيّن كأنها غلط.
    func arrange<T: BoardIdentifiable>(_ cards: [T]) -> [T] {
        guard !order.isEmpty else { return cards }
        let rank = Dictionary(uniqueKeysWithValues: order.enumerated().map { ($1, $0) })
        var inherited: [String: Double] = [:]
        var last = -1.0
        var run = 0
        for c in cards {
            if let r = rank[c.boardID] { last = Double(r); run = 0 } else {
                run += 1
                inherited[c.boardID] = last + Double(run) / 1000
            }
        }
        return cards.sorted {
            (rank[$0.boardID].map(Double.init) ?? inherited[$0.boardID] ?? 0)
                < (rank[$1.boardID].map(Double.init) ?? inherited[$1.boardID] ?? 0)
        }
    }

    var isCustomised: Bool { !order.isEmpty || !scales.isEmpty }

    // ── كتابة ────────────────────────────────────────────────────────────────

    /// أثناء السحب: بنغيّر بلا حفظ.
    ///
    /// السحب بيولّد عشرات التحديثات بالثانية، وكتابة القرص مع كل وحدة بتخلّي
    /// الإصبع تتعتّر. الحفظ بيصير مرّة لما ترفع إيدك.
    func setScale(_ v: Double, for id: String) {
        scales[id] = min(max(v, Self.minScale), Self.maxScale)
    }

    func setOrder(_ ids: [String]) { order = ids; save() }

    func reset() { scales = [:]; order = []; save() }

    func save() {
        let d = UserDefaults.standard
        d.set(scales, forKey: "\(key).scales")
        d.set(order, forKey: "\(key).order")
    }

    private func load() {
        let d = UserDefaults.standard
        scales = (d.dictionary(forKey: "\(key).scales") as? [String: Double]) ?? [:]
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
