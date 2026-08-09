import SwiftUI


/// يحمل عنوان الزر + التبويب الهدف للفعل السياقي.
struct ProactiveAction {
    let title: String
    let target: MainTab
}


/// عناصر الرئيسية القابلة لإعادة الترتيب (التحية تبقى ترويسة ثابتة فوق). كل عنصر
/// له مفتاح عنوان وأيقونة لعرضه بورقة إعادة الترتيب.
enum HomeBlock: String, CaseIterable, Identifiable {
    case proactive, glance
    var id: String { rawValue }
    var titleKey: String {
        switch self {
        case .proactive: return "home.block.proactive"
        case .glance:    return "home.block.glance"
        }
    }
    var icon: String {
        switch self {
        case .proactive: return "sparkles"
        case .glance:    return "square.grid.2x2.fill"
        }
    }
}
