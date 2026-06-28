import SwiftUI

/// تبويب ساندي — مركز الذكاء الموحّد. الشات هو السطح الأساسي (المحرّك اللي بيعمل
/// أي شي بالأوامر)، والبحث وتوليد الصور بمتناول اليد عبر مبدّل وضع علوي. وزر
/// «أدوات ساندي» بجنب المبدّل يفتح أدواتها الأخرى (تسوّق/كتب/ألبوم/محتوى يهمّك)
/// كشاشات كاملة. هيك تبقى كل قدرات ساندي بمكان واحد (رؤية "Unified AI Hub").
struct SandyHubView: View {
    @EnvironmentObject var lang: LanguageManager

    /// وضع الهَب — محادثة (افتراضي) / بحث / صور.
    enum Mode: String, CaseIterable { case chat, search, images }
    @State private var mode: Mode = .chat
    /// ورقة أدوات ساندي (التسوّق/الكتب/الألبوم/المحتوى).
    @State private var showTools = false

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: Theme.Spacing.sm) {
                modePicker
                toolsButton
            }
            .padding(.horizontal, Theme.Spacing.md)
            .padding(.top, Theme.Spacing.sm)

            // العرض المختار يملأ باقي المساحة — كل واجهة تجيب عنوانها وتولباراتها
            // الخاصة (مثلاً سجل الشات + زر صوت ساندي يظهروا بوضع المحادثة فقط).
            switch mode {
            case .chat:   ChatView()
            case .search: SearchView()
            case .images: ImagesView()
            }
        }
        // الخلفية موحّدة على مستوى MainTabView — لا نكرّرها هون (طبقة مهدورة).
        .sheet(isPresented: $showTools) { SandyToolsSheet() }
    }

    private var modePicker: some View {
        Picker("", selection: $mode) {
            Text(lang.s("sandy.mode.chat")).tag(Mode.chat)
            Text(lang.s("sandy.mode.search")).tag(Mode.search)
            Text(lang.s("sandy.mode.images")).tag(Mode.images)
        }
        .pickerStyle(.segmented)
    }

    private var toolsButton: some View {
        Button { showTools = true } label: {
            Image(systemName: "square.grid.2x2.fill")
                .font(.system(size: 18, weight: .semibold))
                .foregroundColor(Theme.Colors.accent)
        }
        .accessibilityLabel(lang.s("sandy.tools"))
    }
}

// MARK: - ورقة أدوات ساندي

/// أدوات ساندي الأخرى — التسوّق/الكتب/الألبوم/المحتوى اللي يهمّك. كل أداة شاشتها
/// الكاملة تُفتح كدفعة من هون، فيبقى الشات هو الواجهة الأساسية بتبويب ساندي.
private struct SandyToolsSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                SandyBackground()
                ScrollView {
                    VStack(spacing: Theme.Spacing.md) {
                        toolRow(icon: "cart.fill", titleKey: "sandy.shopping") { ShoppingView() }
                        toolRow(icon: "books.vertical.fill", titleKey: "sandy.books") { BooksView() }
                        toolRow(icon: "photo.stack.fill", titleKey: "sandy.photos") { PhotosView() }
                        toolRow(icon: "sparkles", titleKey: "sandy.share") { ShareContentView() }
                    }
                    .padding(Theme.Spacing.md)
                }
            }
            .navigationTitle(lang.s("sandy.tools"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("common.done")) { dismiss() }
                }
            }
        }
    }

    @ViewBuilder
    private func toolRow<Destination: View>(
        icon: String, titleKey: String,
        @ViewBuilder destination: @escaping () -> Destination
    ) -> some View {
        NavigationLink {
            destination()
        } label: {
            HStack(spacing: Theme.Spacing.md) {
                Image(systemName: icon)
                    .font(.title3)
                    .foregroundColor(Theme.Colors.accent)
                    .frame(width: 30)
                Text(lang.s(titleKey))
                    .font(.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                Spacer(minLength: 0)
                Image(systemName: "chevron.left")
                    .foregroundColor(Theme.Colors.secondaryText)
            }
            .sandyCard()
        }
        .buttonStyle(.plain)
    }
}
