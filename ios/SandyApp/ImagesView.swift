import SwiftUI
import PhotosUI

/// وضع الصور — توليد من نص، تعديل صورة موجودة، أو وصف صورة.
enum ImageMode: Hashable { case generate, edit, describe }

/// تبويب الصور — توليد (Azure FLUX) عبر `/api/image`، تعديل عبر `/api/image/edit`،
/// ووصف عبر `/api/analyze-image`. نمط الستور المعتمد: العملية تجري في مهمة يملكها
/// الستور، فإلغاء إيماءة الواجهة ما يلغيها.
struct ImagesView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = ImagesStore()
    @State private var mode: ImageMode = .generate
    @State private var prompt = ""
    @State private var question = ""
    @State private var pickedItem: PhotosPickerItem?
    @State private var sourceImage: UIImage?

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                modePicker

                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                content
            }
        }
        .navigationTitle(lang.s("tabs.images"))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .onChange(of: mode) { _ in store.reset() }
        .onChange(of: pickedItem) { item in loadPicked(item) }
    }

    private var modePicker: some View {
        Picker("", selection: $mode) {
            Text(lang.s("images.mode.generate")).tag(ImageMode.generate)
            Text(lang.s("images.mode.edit")).tag(ImageMode.edit)
            Text(lang.s("images.mode.describe")).tag(ImageMode.describe)
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, Theme.Spacing.sm)
    }

    @ViewBuilder
    private var content: some View {
        ScrollView {
            VStack(spacing: Theme.Spacing.md) {
                switch mode {
                case .generate: generateSection
                case .edit:     editSection
                case .describe: describeSection
                }

                if store.loading {
                    ProgressView().tint(Theme.Colors.accent).padding(.top, Theme.Spacing.lg)
                }

                resultSection
            }
            .padding(Theme.Spacing.md)
            .padding(.bottom, Theme.Spacing.xxl + Theme.Spacing.xl)
        }
    }

    // MARK: - أقسام الأوضاع

    private var generateSection: some View {
        VStack(spacing: Theme.Spacing.md) {
            promptField(lang.s("images.promptPlaceholder"), $prompt)
            SandyButton(title: lang.s("images.generate"),
                        systemImage: "sparkles", isLoading: store.loading, fillWidth: true) {
                let p = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !p.isEmpty else { return }
                Task { await store.generate(api: state.api, prompt: p) }
            }
        }
    }

    private var editSection: some View {
        VStack(spacing: Theme.Spacing.md) {
            pickerButton
            sourcePreview
            promptField(lang.s("images.editPlaceholder"), $prompt)
            SandyButton(title: lang.s("images.edit"),
                        systemImage: "wand.and.stars", isLoading: store.loading, fillWidth: true) {
                let p = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
                guard let img = sourceImage, !p.isEmpty else { return }
                Task { await store.edit(api: state.api, image: img, prompt: p) }
            }
            .disabled(sourceImage == nil)
        }
    }

    private var describeSection: some View {
        VStack(spacing: Theme.Spacing.md) {
            pickerButton
            sourcePreview
            promptField(lang.s("images.questionPlaceholder"), $question)
            SandyButton(title: lang.s("images.describe"),
                        systemImage: "text.viewfinder", isLoading: store.loading, fillWidth: true) {
                guard let img = sourceImage else { return }
                Task {
                    await store.describe(api: state.api, image: img,
                                         question: question.trimmingCharacters(in: .whitespacesAndNewlines))
                }
            }
            .disabled(sourceImage == nil)
        }
    }

    // MARK: - عناصر مشتركة

    private func promptField(_ placeholder: String, _ value: Binding<String>) -> some View {
        TextField(placeholder, text: value, axis: .vertical)
            .lineLimit(1...4)
            .padding(Theme.Spacing.sm)
            .background(RoundedRectangle(cornerRadius: Theme.Radius.control).fill(.ultraThinMaterial))
    }

    private var pickerButton: some View {
        PhotosPicker(selection: $pickedItem, matching: .images) {
            Label(sourceImage == nil ? lang.s("images.pick") : lang.s("images.pickAgain"),
                  systemImage: "photo.on.rectangle")
                .font(Theme.Typography.button)
                .foregroundColor(Theme.Colors.accent)
                .frame(maxWidth: .infinity)
                .padding(Theme.Spacing.sm)
                .background(RoundedRectangle(cornerRadius: Theme.Radius.control)
                    .stroke(Theme.Colors.accent.opacity(0.4), lineWidth: 1))
        }
    }

    @ViewBuilder
    private var sourcePreview: some View {
        if let img = sourceImage {
            Image(uiImage: img)
                .resizable().scaledToFit()
                .frame(maxHeight: 200)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control))
        }
    }

    @ViewBuilder
    private var resultSection: some View {
        if let img = store.resultImage {
            SandyCard {
                VStack(spacing: Theme.Spacing.sm) {
                    Image(uiImage: img)
                        .resizable().scaledToFit()
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control))
                    ShareLink(item: Image(uiImage: img),
                              preview: SharePreview(lang.s("tabs.images"), image: Image(uiImage: img))) {
                        Label(lang.s("images.share"), systemImage: "square.and.arrow.up")
                            .font(Theme.Typography.button)
                            .foregroundColor(Theme.Colors.accent)
                    }
                }
            }
        }
        if !store.caption.isEmpty {
            SandyCard {
                Text(store.caption)
                    .font(Theme.Typography.body)
                    .foregroundColor(Theme.Colors.primaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private func loadPicked(_ item: PhotosPickerItem?) {
        guard let item else { return }
        Task {
            if let data = try? await item.loadTransferable(type: Data.self),
               let img = UIImage(data: data) {
                await MainActor.run {
                    sourceImage = img
                    store.reset()
                }
            }
        }
    }
}

// MARK: - الستور (مصدر الحقيقة لناتج الصور)

@MainActor
final class ImagesStore: ObservableObject {
    @Published var resultImage: UIImage?    // ناتج التوليد/التعديل
    @Published var caption = ""             // ناتج الوصف
    @Published var loading = false
    @Published var notice = ""

    private var task: Task<Void, Never>?

    /// يصفّي النواتج (عند تبديل الوضع أو اختيار صورة جديدة).
    func reset() {
        resultImage = nil
        caption = ""
        notice = ""
    }

    func generate(api: APIClient, prompt: String) async {
        await run {
            let data = try await api.generateImage(prompt: prompt)
            self.resultImage = UIImage(data: data)
            if self.resultImage == nil { self.notice = LanguageManager.shared.s("images.error") }
        }
    }

    func edit(api: APIClient, image: UIImage, prompt: String) async {
        guard let data = image.jpegData(compressionQuality: 0.9) else {
            notice = LanguageManager.shared.s("images.error"); return
        }
        await run {
            let out = try await api.editImage(image: data, prompt: prompt)
            self.resultImage = UIImage(data: out)
            if self.resultImage == nil { self.notice = LanguageManager.shared.s("images.error") }
        }
    }

    func describe(api: APIClient, image: UIImage, question: String) async {
        guard let data = image.jpegData(compressionQuality: 0.9) else {
            notice = LanguageManager.shared.s("images.error"); return
        }
        await run {
            self.caption = try await api.describeImage(image: data, question: question)
        }
    }

    /// يلفّ العملية بمهمة يملكها الستور (محصّنة ضد إلغاء الإيماءة) وينتظرها، مع
    /// معالجة خطأ موحّدة.
    private func run(_ op: @escaping () async throws -> Void) async {
        task?.cancel()
        let t = Task { @MainActor in
            loading = true; notice = ""
            defer { loading = false }
            do { try await op() }
            catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("images.error") }
            }
        }
        task = t
        await t.value
    }
}
