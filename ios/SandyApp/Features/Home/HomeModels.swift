import SwiftUI

/// يحمل عنوان الزر + التبويب الهدف للفعل السياقي.
struct ProactiveAction {
    let title: String
    let target: MainTab
}

/// عناصر الرئيسية القابلة لإعادة الترتيب (التحية تبقى ترويسة ثابتة فوق). كل عنصر