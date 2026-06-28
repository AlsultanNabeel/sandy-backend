import SwiftUI

/// تبويب ساندي — مركز الذكاء الموحّد. الشات هو السطح الأساسي (المحرّك اللي بيعمل
/// أي شي بالأوامر)، والبحث وتوليد الصور بمتناول اليد عبر مبدّل وضع علوي. هيك تبقى
/// كل قدرات ساندي بمكان واحد بدل تبويبات منفصلة (رؤية "Unified AI Hub").
struct SandyHubView: View {
    @EnvironmentObject var lang: LanguageManager

    /// وضع الهَب — محادثة (افتراضي) / بحث / صور.
    enum Mode: String, CaseIterable { case chat, search, images }
    @State private var mode: Mode = .chat

    var body: some View {
        VStack(spacing: 0) {
            modePicker
            // العرض المختار يملأ باقي المساحة — كل واجهة تجيب عنوانها وتولباراتها
            // الخاصة (مثلاً سجل الشات + زر صوت ساندي يظهروا بوضع المحادثة فقط).
            switch mode {
            case .chat:   ChatView()
            case .search: SearchView()
            case .images: ImagesView()
            }
        }
        .background(SandyBackground())
    }

    private var modePicker: some View {
        Picker("", selection: $mode) {
            Text(lang.s("sandy.mode.chat")).tag(Mode.chat)
            Text(lang.s("sandy.mode.search")).tag(Mode.search)
            Text(lang.s("sandy.mode.images")).tag(Mode.images)
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, Theme.Spacing.sm)
    }
}
