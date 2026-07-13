import SwiftUI
import PhotosUI

@MainActor
final class ImagesStore: LoadableStore {
    @Published var resultImage: UIImage?    // ناتج التوليد/التعديل
    @Published var caption = ""             // ناتج الوصف

    private var task: Task<Void, Never>?

    /// يصفّي النواتج (عند تبديل الوضع أو اختيار صورة جديدة).
    func reset() {
        resultImage = nil
        caption = ""
        clearNotice()
    }

    func generate(api: APIClient, prompt: String) async {
        await run {
            let data = try await api.generateImage(prompt: prompt)
            self.resultImage = UIImage(data: data)
            if self.resultImage == nil { self.notify("images.error") }
        }
    }

    func edit(api: APIClient, image: UIImage, prompt: String) async {
        guard let data = image.jpegData(compressionQuality: 0.9) else {
            notify("images.error"); return
        }
        await run {
            let out = try await api.editImage(image: data, prompt: prompt)
            self.resultImage = UIImage(data: out)
            if self.resultImage == nil { self.notify("images.error") }
        }
    }

    func describe(api: APIClient, image: UIImage, question: String) async {
        guard let data = image.jpegData(compressionQuality: 0.9) else {
            notify("images.error"); return
        }
        await run {
            self.caption = try await api.describeImage(image: data, question: question)
        }
    }

    /// يلفّ العملية بمهمة يملكها الستور (محصّنة ضد إلغاء الإيماءة) وينتظرها، مع
    /// معالجة خطأ موحّدة.
    private func run(_ op: @escaping @MainActor () async throws -> Void) async {
        task?.cancel()
        let t = Task { @MainActor in
            loading = true; clearNotice()
            defer { loading = false }
            do { try await op() }
            catch {
                if !error.isCancellation { notify("images.error") }
            }
        }
        task = t
        await t.value
    }
}
