import SwiftUI

/// مدخل جسم ساندي من الرئيسية.
///
/// موجود لأن `RobotControlView` بتاخد ستور جاهز — صفحة التحكّم بالبيت عندها
/// واحد وبتمرّره. الرئيسية ما عندها، فهاي بتملك واحد وبتجيب البيانات.
///
/// ستور مستقل مش مشارَك: الصفحتين بيتفتحوا من مكانين مختلفين وبأوقات مختلفة،
/// ومشاركة ستور بين شاشتين ما بينفتحوا سوا بتخلّي وحدة تعتمد ع إنه التانية
/// انفتحت قبلها — وهاد بيشتغل بالتجربة وبيفشل عند المستخدم.
struct RobotHomeEntry: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store = DevicesStore()

    var body: some View {
        RobotControlView(store: store)
            .environmentObject(state)
            .environmentObject(lang)
            .task { await store.load(api: state.api) }
    }
}
