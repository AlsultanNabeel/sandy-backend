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

    /// ترتيب أثناء السحب — بلا حفظ.
    ///
    /// السحب بيعيد الترتيب عشرات المرّات بالثانية وإنت ماسك، وكتابة القرص مع
    /// كل وحدة بتخلّي الإصبع تتعتّر. الحفظ بيصير مرّة لما ترفع إيدك.
    func setOrderLive(_ ids: [String]) { order = ids }

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
