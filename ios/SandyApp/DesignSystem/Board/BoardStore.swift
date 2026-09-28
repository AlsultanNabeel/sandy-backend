import SwiftUI

/// مقاس بطاقة وترتيبها، لكل صفحة على حدة.
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


    func size(_ id: String, default def: CardSize) -> CardSize {
        sizes[id] ?? def
    }

    /// بترتيب المستخدم؛ الرُّتَب بخطوة مستقلة بأنواع صريحة، وإلا المترجم بيعجز عن فحص التعبير.
    func arrange<T: BoardIdentifiable>(_ cards: [T]) -> [T] {
        guard !order.isEmpty else { return cards }

        var rank: [String: Double] = [:]
        for (i, id) in order.enumerated() {
            rank[id] = Double(i)
        }

        // بطاقة بلا ترتيب محفوظ (جديدة) بتقعد جنب اللي قبلها بالكود، مش بالآخر.
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


    /// المقاس بينحفظ لحظة ما يتغيّر.
    func setSize(_ v: CardSize, for id: String) {
        sizes[id] = v
        save()
    }

    func setOrder(_ ids: [String]) { order = ids; save() }

    /// بلا حفظ: السحب بيعيد الترتيب عشرات المرّات بالثانية؛ الحفظ لما ترفع إيدك.
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

/// المعرّف نص ثابت مش موقع بالمصفوفة، حتى إضافة بطاقة ما تخربط ترتيب المستخدمين.
protocol BoardIdentifiable {
    var boardID: String { get }
}
