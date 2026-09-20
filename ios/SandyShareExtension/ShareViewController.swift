import SwiftUI
import UIKit
import UniformTypeIdentifiers

// ─────────────────────────────────────────────────────────────────────────
//  SandyShare — «شارك مع ساندي» من أي تطبيق: رابط، نص، أو صورة وحدة.
//
//  تلات أفعال:
//   • لخّصلي     → نص/رابط: POST /api/agent · صورة: POST /api/analyze-image
//   • احفظه      → نص: POST /api/memory · رابط: /api/share/saved + /api/memory
//                  · صورة: POST /api/photos (ألبوم الصور)
//   • حوّله لمهمة → POST /api/tasks (الصورة بتنوصف أول بسطر قصير)
//
//  الإضافة تارجت منفصل ما بيشوف كود التطبيق — شوف README.md بهالمجلّد.
// ─────────────────────────────────────────────────────────────────────────

final class ShareViewController: UIViewController {
    private var model: ShareModel?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 0.008, green: 0.020, blue: 0.031, alpha: 1) // #020508

        let model = ShareModel(context: extensionContext)
        self.model = model
        let host = UIHostingController(rootView: ShareSheetView(model: model))
        host.view.backgroundColor = .clear
        host.view.translatesAutoresizingMaskIntoConstraints = false
        addChild(host)
        view.addSubview(host.view)
        NSLayoutConstraint.activate([
            host.view.topAnchor.constraint(equalTo: view.topAnchor),
            host.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            host.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            host.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])
        host.didMove(toParent: self)

        Task { await model.loadInput() }
    }
}

// MARK: - الحالة

enum ShareAction {
    case summarize, save, task
}

@MainActor
final class ShareModel: ObservableObject {
    @Published var text: String?
    @Published var url: URL?
    @Published var imageData: Data?
    @Published var loadingInput = true
    @Published var busy: ShareAction?
    @Published var result: String?
    @Published var error: String?

    private weak var context: NSExtensionContext?

    init(context: NSExtensionContext?) {
        self.context = context
    }

    var hasContent: Bool {
        imageData != nil || url != nil || !(text ?? "").isEmpty
    }

    // MARK: قراءة اللي انشارك

    func loadInput() async {
        let items = (context?.inputItems as? [NSExtensionItem]) ?? []
        var foundText: String?
        var foundURL: URL?
        var foundImage: Data?
        for item in items {
            if foundText == nil, let t = item.attributedContentText?.string,
               !t.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                foundText = t
            }
            for provider in item.attachments ?? [] {
                if foundImage == nil, provider.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
                    foundImage = await Self.loadImage(provider)
                } else if foundURL == nil, provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                    if let u = await Self.loadURL(provider), !u.isFileURL { foundURL = u }
                } else if foundText == nil, provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                    foundText = await Self.loadText(provider)
                }
            }
        }
        // نص هو بالأصل رابط (بعض التطبيقات بتشارك هيك).
        if foundURL == nil, let t = foundText?.trimmingCharacters(in: .whitespacesAndNewlines),
           !t.contains(" "), let u = URL(string: t), let scheme = u.scheme?.lowercased(),
           scheme == "http" || scheme == "https" {
            foundURL = u
            foundText = nil
        }
        text = foundText
        url = foundURL
        imageData = foundImage
        loadingInput = false
    }

    private static func loadItem(_ provider: NSItemProvider, _ type: UTType) async -> Any? {
        await withCheckedContinuation { (cont: CheckedContinuation<Any?, Never>) in
            provider.loadItem(forTypeIdentifier: type.identifier, options: nil) { value, _ in
                cont.resume(returning: value)
            }
        }
    }

    private static func loadURL(_ provider: NSItemProvider) async -> URL? {
        let value = await loadItem(provider, .url)
        if let u = value as? URL { return u }
        if let s = value as? String { return URL(string: s) }
        if let d = value as? Data { return URL(dataRepresentation: d, relativeTo: nil) }
        return nil
    }

    private static func loadText(_ provider: NSItemProvider) async -> String? {
        let value = await loadItem(provider, .plainText)
        if let s = value as? String { return s }
        if let a = value as? NSAttributedString { return a.string }
        if let d = value as? Data { return String(data: d, encoding: .utf8) }
        return nil
    }

    /// الصورة كـ JPEG مصغّرة — إضافات المشاركة ذاكرتها محدودة، والرفع أسرع.
    private static func loadImage(_ provider: NSItemProvider) async -> Data? {
        let value = await loadItem(provider, .image)
        var image: UIImage?
        if let i = value as? UIImage { image = i }
        else if let d = value as? Data { image = UIImage(data: d) }
        else if let u = value as? URL, let d = try? Data(contentsOf: u) { image = UIImage(data: d) }
        guard let image else { return nil }
        return downscaled(image, maxSide: 1600).jpegData(compressionQuality: 0.8)
    }

    private static func downscaled(_ image: UIImage, maxSide: CGFloat) -> UIImage {
        let side = max(image.size.width, image.size.height)
        guard side > maxSide else { return image }
        let scale = maxSide / side
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        return UIGraphicsImageRenderer(size: size, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
    }

    // MARK: الأفعال

    /// النص اللي منبعته للوكيل: الرابط + أي نص رافقه.
    private var contentLine: String {
        var parts: [String] = []
        if let t = text?.trimmingCharacters(in: .whitespacesAndNewlines), !t.isEmpty { parts.append(t) }
        if let u = url { parts.append(u.absoluteString) }
        return String(parts.joined(separator: "\n").prefix(6000))
    }

    func run(_ action: ShareAction) async {
        guard busy == nil else { return }
        guard let api = ShareAPI.load() else {
            error = ShareError.signedOut.errorDescription
            return
        }
        busy = action
        error = nil
        result = nil
        defer { busy = nil }
        do {
            switch action {
            case .summarize: result = try await summarize(api)
            case .save: result = try await save(api)
            case .task: result = try await makeTask(api)
            }
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        } catch {
            self.error = error.localizedDescription
            UINotificationFeedbackGenerator().notificationOccurred(.error)
        }
    }

    private func summarize(_ api: ShareAPI) async throws -> String {
        if let img = imageData {
            let res = try await api.post("/api/analyze-image", [
                "image": img.base64EncodedString(),
                "question": ShareText.t("لخّصلي شو في بهالصورة", "Summarize what's in this image"),
            ], timeout: 90)
            return (res["reply"] as? String) ?? ""
        }
        let prompt = ShareText.t("لخّصلي هاد: ", "Summarize this for me: ") + contentLine
        let res = try await api.post("/api/agent", ["message": prompt], timeout: 90)
        return (res["reply"] as? String) ?? ""
    }

    private func save(_ api: ShareAPI) async throws -> String {
        if let img = imageData {
            _ = try await api.post("/api/photos", [
                "image": img.base64EncodedString(),
                "name": text ?? "",
            ], timeout: 90)
            return ShareText.t("انحفظت الصورة بألبوم ساندي.", "Saved the photo to Sandy's album.")
        }
        if let u = url {
            let title = (text?.trimmingCharacters(in: .whitespacesAndNewlines)).flatMap { $0.isEmpty ? nil : $0 }
                ?? (u.host ?? u.absoluteString)
            _ = try await api.post("/api/share/saved", ["url": u.absoluteString, "title": title])
        }
        let memo = ShareText.t("حفظت هاد: ", "Saved this: ") + contentLine
        _ = try await api.post("/api/memory", ["text": memo])
        return ShareText.t("انحفظ بذاكرة ساندي.", "Saved to Sandy's memory.")
    }

    private func makeTask(_ api: ShareAPI) async throws -> String {
        var title: String
        var note = ""
        if let img = imageData {
            let res = try await api.post("/api/analyze-image", [
                "image": img.base64EncodedString(),
                "question": ShareText.t(
                    "اكتب عنوان مهمة وحدة قصيرة (أقل من عشر كلمات) من هالصورة، بدون أي شرح",
                    "Write one short task title (under ten words) from this image, with no explanation"),
            ], timeout: 90)
            title = ((res["reply"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        } else {
            let t = (text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let firstLine = t.split(separator: "\n").first.map(String.init) ?? ""
            if !firstLine.isEmpty {
                title = String(firstLine.prefix(120))
            } else if let u = url {
                title = ShareText.t("اقرأ: ", "Read: ") + (u.host ?? u.absoluteString)
            } else {
                title = ""
            }
            if let u = url { note = u.absoluteString }
            if t.count > title.count { note = note.isEmpty ? String(t.prefix(2000)) : note + "\n" + String(t.prefix(2000)) }
        }
        if title.isEmpty { title = ShareText.t("مهمة من المشاركة", "Task from share") }
        _ = try await api.post("/api/tasks", ["text": title, "note": note])
        return ShareText.t("ضفت المهمة: ", "Added task: ") + title
    }

    // MARK: الإغلاق

    func close() {
        context?.completeRequest(returningItems: nil, completionHandler: nil)
    }
}

// MARK: - الواجهة

private enum SharePalette {
    static let background = Color(red: 0.008, green: 0.020, blue: 0.031)   // #020508
    static let card = Color(red: 0.039, green: 0.078, blue: 0.133)         // ~#0A1422
    static let accent = Color(red: 0.0, green: 0.831, blue: 1.0)           // #00D4FF
    static let onAccent = Color(red: 0.008, green: 0.071, blue: 0.110)
    static let text = Color(red: 0.941, green: 0.980, blue: 1.0)
    static let secondary = Color(red: 0.616, green: 0.698, blue: 0.776)
    static let warning = Color(red: 1.0, green: 0.741, blue: 0.349)
}

struct ShareSheetView: View {
    @ObservedObject var model: ShareModel

    private var ar: Bool { ShareText.isArabic }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            header
            if model.loadingInput {
                ProgressView().tint(SharePalette.accent).frame(maxWidth: .infinity)
            } else if !model.hasContent {
                Text(ShareText.t("ما لقيت شي أشاركه.", "Nothing to share here."))
                    .foregroundStyle(SharePalette.secondary)
            } else {
                preview
                actions
            }
            if let error = model.error {
                Text(error)
                    .font(.callout)
                    .foregroundStyle(SharePalette.warning)
            }
            if let result = model.result {
                ScrollView {
                    Text(result)
                        .font(.body)
                        .foregroundStyle(SharePalette.text)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(12)
                .background(SharePalette.card, in: RoundedRectangle(cornerRadius: 14))
            }
            Spacer(minLength: 0)
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(SharePalette.background.ignoresSafeArea())
        .environment(\.layoutDirection, ar ? .rightToLeft : .leftToRight)
        .preferredColorScheme(.dark)
    }

    private var header: some View {
        HStack {
            Image(systemName: "sparkles").foregroundStyle(SharePalette.accent)
            Text(ShareText.t("شارك مع ساندي", "Share with Sandy"))
                .font(.headline)
                .foregroundStyle(SharePalette.text)
            Spacer()
            Button(ShareText.t("تم", "Done")) { model.close() }
                .foregroundStyle(SharePalette.accent)
        }
    }

    @ViewBuilder
    private var preview: some View {
        HStack(alignment: .top, spacing: 12) {
            if let data = model.imageData, let image = UIImage(data: data) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
                    .frame(width: 64, height: 64)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }
            VStack(alignment: .leading, spacing: 4) {
                if let t = model.text, !t.isEmpty {
                    Text(t).lineLimit(3).foregroundStyle(SharePalette.text)
                }
                if let u = model.url {
                    Text(u.absoluteString).lineLimit(1).font(.footnote)
                        .foregroundStyle(SharePalette.accent)
                        .environment(\.layoutDirection, .leftToRight)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(SharePalette.card, in: RoundedRectangle(cornerRadius: 14))
    }

    private var actions: some View {
        VStack(spacing: 10) {
            actionButton(.summarize, icon: "text.alignleft", title: ShareText.t("لخّصلي", "Summarize"))
            actionButton(.save, icon: "tray.and.arrow.down.fill", title: ShareText.t("احفظه", "Save it"))
            actionButton(.task, icon: "checklist", title: ShareText.t("حوّله لمهمة", "Make it a task"))
        }
    }

    private func actionButton(_ action: ShareAction, icon: String, title: String) -> some View {
        let primary = action == .summarize
        return Button {
            Task { await model.run(action) }
        } label: {
            HStack(spacing: 10) {
                if model.busy == action {
                    ProgressView().tint(primary ? SharePalette.onAccent : SharePalette.accent)
                } else {
                    Image(systemName: icon)
                }
                Text(title).fontWeight(.semibold)
                Spacer()
            }
            .padding(.horizontal, 16)
            .frame(height: 50)
            .foregroundStyle(primary ? SharePalette.onAccent : SharePalette.accent)
            .background(primary ? SharePalette.accent : SharePalette.card,
                        in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14)
                .stroke(SharePalette.accent.opacity(primary ? 0 : 0.35), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .disabled(model.busy != nil)
    }
}
