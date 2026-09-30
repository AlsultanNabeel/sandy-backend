import Foundation

// نسخ Codable من نماذج القوائم للكاش: النماذج الأصلية مش Codable، وتوليد Codable
// تلقائيًا ممنوع بامتداد بملف تاني.

struct CachedList<M: Codable>: Codable {
    let items: [M]
    let demo: Bool
}

struct CachedMemoryFact: Codable {
    let id, text, type: String
    init(_ f: MemoryFact) { id = f.id; text = f.text; type = f.type }
    var model: MemoryFact { MemoryFact(id: id, text: text, type: type) }
}

struct CachedPlan: Codable {
    let id, topic, summary, finishedAt, planText: String
    init(_ p: ProjectPlan) {
        id = p.id; topic = p.topic; summary = p.summary; finishedAt = p.finishedAt; planText = p.planText
    }
    var model: ProjectPlan {
        ProjectPlan(id: id, topic: topic, summary: summary, finishedAt: finishedAt, planText: planText)
    }
}
