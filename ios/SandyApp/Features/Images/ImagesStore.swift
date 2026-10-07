import SwiftUI
import PhotosUI

@MainActor
final class ImagesStore: LoadableStore {
    @Published var resultImage: UIImage?    // ناتج التوليد/التعديل
    @Published var caption = ""             // ناتج الوصف

    private var task: Task<Void, Never>?

    /// يصفّي النواتج (عند تبديل الوضع أو اختيار صورة جديدة). A request still running is
    /// called off, or its picture would land under the mode switched to.
    func reset() {
        task?.cancel()
        task = nil
        endLoad(beginLoad())
        resultImage = nil
        caption = ""
        clearNotice()
    }

    func generate(api: APIClient, prompt: String) async {
        await run {
            let data = try await api.generateImage(prompt: prompt)
            try Task.checkCancellation()
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
            try Task.checkCancellation()
            self.resultImage = UIImage(data: out)
            if self.resultImage == nil { self.notify("images.error") }
        }
    }

    func describe(api: APIClient, image: UIImage, question: String) async {
        guard let data = image.jpegData(compressionQuality: 0.9) else {
            notify("images.error"); return
        }
        await run {
            let caption = try await api.describeImage(image: data, question: question)
            try Task.checkCancellation()
            self.caption = caption
        }
    }

    /// يلفّ العملية بمهمة يملكها الستور (محصّنة ضد إلغاء الإيماءة) وينتظرها، مع
    /// معالجة خطأ موحّدة.
    private func run(_ op: @escaping @MainActor () async throws -> Void) async {
        task?.cancel()
        let gen = beginLoad()
        let t = Task { @MainActor in
            clearNotice()
            defer { endLoad(gen) }
            do { try await op() }
            catch {
                if !error.isCancellation, isCurrentLoad(gen) { notify("images.error") }
            }
        }
        task = t
        await t.value
    }
}
