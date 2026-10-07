import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

// Chat attachments: what is picked waits above the field (with its upload progress and
// an ✕), goes up at once, and is sent with the next message. In the thread, photos and
// the images Sandy draws show inside their bubble; a tap opens them full screen.

// MARK: - Picking and uploading

@MainActor
final class AttachmentComposer: ObservableObject {
    struct Pending: Identifiable {
        let id = UUID()
        let name: String
        let isImage: Bool
        let preview: UIImage?
        var progress: Double = 0
        var uploaded: ChatAttachment?
        var error: String?
    }

    @Published private(set) var items: [Pending] = []
    private var uploads: [UUID: Task<Void, Never>] = [:]

    /// Uploaded and ready to go with the message.
    var ready: [ChatAttachment] { items.compactMap(\.uploaded) }
    /// Still going up: the send waits.
    var busy: Bool { items.contains { $0.uploaded == nil && $0.error == nil } }
    var isFull: Bool { items.count >= Self.maxItems }

    static let maxItems = 4
    /// Longest side of a photo sent to Sandy, in pixels: plenty to see, a fraction of the bytes.
    nonisolated static let maxSide: CGFloat = 1600

    /// A photo from the library, made small from its file bytes, off the main thread.
    func addPhoto(_ data: Data, api: APIClient) {
        guard !isFull else { return }
        Task {
            let jpeg = await Task.detached(priority: .userInitiated) { Self.jpeg(from: data) }.value
            if let jpeg { add(jpeg, api: api) }
        }
    }

    /// A photo from the camera, made small off the main thread.
    func addImage(_ image: UIImage, api: APIClient) {
        guard !isFull else { return }
        Task {
            let jpeg = await Task.detached(priority: .userInitiated) { Self.jpeg(image) }.value
            if let jpeg { add(jpeg, api: api) }
        }
    }

    private func add(_ jpeg: Data, api: APIClient) {
        guard !isFull else { return }
        start(Pending(name: "photo.jpg", isImage: true, preview: UIImage(data: jpeg)),
              data: jpeg, mime: "image/jpeg", api: api)
    }

    func addFile(at url: URL, api: APIClient) {
        guard !isFull else { return }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        guard let data = try? Data(contentsOf: url) else { return }
        let mime = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
        start(Pending(name: url.lastPathComponent, isImage: false, preview: nil), data: data, mime: mime, api: api)
    }

    private func start(_ item: Pending, data: Data, mime: String, api: APIClient) {
        items.append(item)
        let id = item.id
        uploads[id] = Task { @MainActor [weak self] in
            do {
                let saved = try await api.uploadAttachment(data, name: item.name, mime: mime) { share in
                    Task { @MainActor in self?.update(id) { $0.progress = share } }
                }
                self?.update(id) { $0.uploaded = saved; $0.progress = 1 }
            } catch {
                guard !error.isCancellation else { return }
                let line = (error as? APIError)?.message ?? LanguageManager.shared.s("chat.uploadFailed")
                self?.update(id) { $0.error = line }
                Announce.say(line)
            }
        }
    }

    private func update(_ id: UUID, _ change: (inout Pending) -> Void) {
        guard let idx = items.firstIndex(where: { $0.id == id }) else { return }
        change(&items[idx])
    }

    func remove(_ id: UUID) {
        uploads.removeValue(forKey: id)?.cancel()
        items.removeAll { $0.id == id }
    }

    /// After sending: the field starts empty again.
    func clear() {
        uploads.values.forEach { $0.cancel() }
        uploads = [:]
        items = []
    }

    /// At most `maxSide` pixels on the long side, decoding only what that size needs.
    nonisolated static func jpeg(from data: Data) -> Data? {
        ImageDownscale.jpeg(from: data, maxPixel: Int(maxSide), quality: 0.8)
    }

    /// At most `maxSide` pixels on the long side. Drawn at one pixel a point: the renderer's
    /// default is the screen's scale, which made a «1600» photo 4800 wide, bigger than it came.
    nonisolated static func jpeg(_ image: UIImage) -> Data? {
        let pixels = CGSize(width: image.size.width * image.scale, height: image.size.height * image.scale)
        let side = max(pixels.width, pixels.height)
        guard side > maxSide else { return image.jpegData(compressionQuality: 0.8) }
        let size = CGSize(width: (pixels.width * maxSide / side).rounded(),
                          height: (pixels.height * maxSide / side).rounded())
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let small = UIGraphicsImageRenderer(size: size, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
        return small.jpegData(compressionQuality: 0.8)
    }
}

/// The paperclip: photos, the camera, or a document.
struct AttachButton: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var composer: AttachmentComposer
    @State private var photos: [PhotosPickerItem] = []
    @State private var showPhotos = false
    @State private var showCamera = false
    @State private var showFiles = false

    static let fileTypes: [UTType] = [.pdf, .plainText, .commaSeparatedText, .json, .html,
                                      UTType("net.daringfireball.markdown") ?? .plainText,
                                      UTType("org.openxmlformats.wordprocessingml.document") ?? .data]

    var body: some View {
        Menu {
            Button { showPhotos = true } label: { Label(lang.s("chat.attachPhotos"), systemImage: "photo.on.rectangle") }
            if UIImagePickerController.isSourceTypeAvailable(.camera) {
                Button { showCamera = true } label: { Label(lang.s("chat.attachCamera"), systemImage: "camera") }
            }
            Button { showFiles = true } label: { Label(lang.s("chat.attachFiles"), systemImage: "doc") }
        } label: {
            Image(systemName: "paperclip")
                .scaledFont(Theme.Icon.md, weight: .semibold)
                .foregroundColor(composer.isFull ? Theme.Colors.tertiaryText : Theme.Colors.secondaryText)
                .frame(width: 40, height: 40)
        }
        .disabled(composer.isFull)
        .accessibilityLabel(lang.s("chat.attach"))
        .photosPicker(isPresented: $showPhotos, selection: $photos,
                      maxSelectionCount: AttachmentComposer.maxItems - composer.items.count, matching: .images)
        .onChange(of: photos) { _, picked in
            photos = []
            for item in picked {
                Task {
                    if let data = try? await item.loadTransferable(type: Data.self) {
                        composer.addPhoto(data, api: state.api)
                    }
                }
            }
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraPicker { image in composer.addImage(image, api: state.api) }
                .ignoresSafeArea()
        }
        .fileImporter(isPresented: $showFiles, allowedContentTypes: Self.fileTypes,
                      allowsMultipleSelection: true) { result in
            for url in (try? result.get()) ?? [] { composer.addFile(at: url, api: state.api) }
        }
    }
}

/// The system camera, for one photo.
private struct CameraPicker: UIViewControllerRepresentable {
    let picked: (UIImage) -> Void
    @Environment(\.dismiss) private var dismiss

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let parent: CameraPicker
        init(_ parent: CameraPicker) { self.parent = parent }

        func imagePickerController(_ picker: UIImagePickerController,
                                   didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            if let image = info[.originalImage] as? UIImage { parent.picked(image) }
            parent.dismiss()
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { parent.dismiss() }
    }
}

/// What waits above the field: a thumbnail or a file chip each, with progress and ✕.
struct AttachmentStrip: View {
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var composer: AttachmentComposer

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Theme.Spacing.sm) {
                ForEach(composer.items) { item in tile(item) }
            }
            .padding(.top, 6)
        }
    }

    private func tile(_ item: AttachmentComposer.Pending) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            ZStack {
                if let preview = item.preview {
                    Image(uiImage: preview).resizable().scaledToFill()
                } else {
                    VStack(spacing: 4) {
                        Image(systemName: "doc.text.fill").scaledFont(Theme.Icon.lg)
                            .foregroundColor(Theme.Colors.accent)
                        Text(item.name).font(Theme.Typography.caption).lineLimit(2)
                            .foregroundColor(Theme.Colors.primaryText)
                    }
                    .padding(6)
                }
                if item.uploaded == nil && item.error == nil {
                    Color.black.opacity(0.35)
                    ProgressView(value: item.progress)
                        .progressViewStyle(.circular)
                        .tint(Theme.Colors.onFill)
                }
            }
            .frame(width: 72, height: 72)
            .background(Theme.Colors.surface)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                .stroke(item.error == nil ? Theme.Colors.border : Theme.Colors.warn, lineWidth: 1))
            .overlay(alignment: .topTrailing) {
                Button { composer.remove(item.id) } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(Theme.Colors.onFill, Color.black.opacity(0.55))
                        .scaledFont(18)
                }
                .offset(x: 6, y: -6)
                .accessibilityLabel(lang.s("chat.removeAttachment"))
            }
            if let error = item.error {
                Text(error).font(Theme.Typography.caption).foregroundColor(Theme.Colors.warn)
                    .frame(width: 140, alignment: .leading).fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(item.isImage ? lang.s("chat.photo") : item.name)
        .accessibilityValue(item.error ?? (item.uploaded == nil ? lang.s("chat.uploading") : ""))
    }
}

// MARK: - In the thread

/// An attachment's picture, or why there is none. The server deletes attachments thirty
/// days after they are saved, so an old chat gets `expired` (404), not a placeholder for ever.
enum AttachmentImage: Equatable {
    case image(UIImage)
    case expired
    case failed
}

/// Bytes of attachments seen this session, so scrolling never fetches twice.
@MainActor
final class AttachmentImages {
    static let shared = AttachmentImages()
    private let cache = NSCache<NSString, UIImage>()

    func load(_ id: String, api: APIClient) async -> AttachmentImage {
        if let hit = cache.object(forKey: id as NSString) { return .image(hit) }
        let data: Data
        do {
            data = try await api.attachmentData(id: id)
        } catch let error as APIError where error.code == "not_found" {
            return .expired
        } catch {
            return .failed
        }
        guard let image = UIImage(data: data) else { return .failed }
        cache.setObject(image, forKey: id as NSString)
        return .image(image)
    }
}

/// A photo or a drawn image in a bubble; a tap opens it to zoom, save or share.
struct AttachmentPicture: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    let attachment: ChatAttachment
    @State private var loaded: AttachmentImage?
    @State private var open = false

    private var image: UIImage? {
        if case .image(let image) = loaded { return image }
        return nil
    }

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image).resizable().scaledToFill()
            } else if loaded == .expired {
                VStack(spacing: Theme.Spacing.sm) {
                    Image(systemName: "clock.badge.xmark").scaledFont(28)
                    Text(lang.s("chat.photoExpired")).font(Theme.Typography.caption)
                        .multilineTextAlignment(.center)
                }
                .foregroundColor(Theme.Colors.secondaryText)
                .padding(Theme.Spacing.md)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Theme.Colors.surface)
            } else {
                SkeletonBlock()
            }
        }
        .frame(width: 220, height: 220)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.bubble, style: .continuous))
        .contentShape(Rectangle())
        .onTapGesture { if image != nil { open = true } }
        .task(id: attachment.id) { loaded = await AttachmentImages.shared.load(attachment.id, api: state.api) }
        .fullScreenCover(isPresented: $open) {
            if let image { ImageViewer(image: image).environmentObject(lang) }
        }
        .accessibilityElement()
        .accessibilityLabel(lang.s(loaded == .expired ? "chat.photoExpired" : "chat.photo"))
        .accessibilityHint(image == nil ? "" : lang.s("chat.photoHint"))
        .accessibilityAddTraits(.isImage)
    }
}

/// A document in a bubble: its icon and name.
struct AttachmentFileChip: View {
    let attachment: ChatAttachment

    var body: some View {
        Label(attachment.name, systemImage: "doc.text.fill")
            .font(Theme.Typography.callout)
            .foregroundColor(Theme.Colors.primaryText)
            .lineLimit(1)
            .padding(.horizontal, Theme.Spacing.md)
            .padding(.vertical, Theme.Spacing.sm)
            .background(Capsule().fill(Theme.Colors.surface))
    }
}

/// Full screen: pinch to zoom, double-tap to fit, save to Photos, share.
struct ImageViewer: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let image: UIImage
    @State private var scale: CGFloat = 1
    @State private var lastScale: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero
    @State private var saved = false

    var body: some View {
        NavigationStack {
            Image(uiImage: image)
                .resizable()
                .scaledToFit()
                .scaleEffect(scale)
                .offset(offset)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color.black)
                .gesture(MagnificationGesture()
                    .onChanged { scale = max(1, lastScale * $0) }
                    .onEnded { _ in lastScale = scale })
                .simultaneousGesture(DragGesture()
                    .onChanged { v in
                        guard scale > 1 else { return }
                        offset = CGSize(width: lastOffset.width + v.translation.width,
                                        height: lastOffset.height + v.translation.height)
                    }
                    .onEnded { _ in lastOffset = offset })
                .onTapGesture(count: 2) {
                    withAnimation(Animation.spring(response: 0.3).reduced) {
                        scale = scale > 1 ? 1 : 2.5
                        lastScale = scale
                        offset = .zero
                        lastOffset = .zero
                    }
                }
                .accessibilityLabel(lang.s("chat.photo"))
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button { dismiss() } label: { Image(systemName: "xmark") }
                            .accessibilityLabel(lang.s("a11y.close"))
                    }
                    ToolbarItemGroup(placement: .primaryAction) {
                        Button {
                            UIImageWriteToSavedPhotosAlbum(image, nil, nil, nil)
                            saved = true
                            Haptics.play(.success)
                            Announce.say(lang.s("chat.saved"))
                        } label: {
                            Image(systemName: saved ? "checkmark" : "square.and.arrow.down")
                        }
                        .accessibilityLabel(lang.s(saved ? "chat.saved" : "chat.save"))
                        ShareLink(item: Image(uiImage: image),
                                  preview: SharePreview(lang.s("chat.photo"), image: Image(uiImage: image))) {
                            Image(systemName: "square.and.arrow.up")
                        }
                        .accessibilityLabel(lang.s("chat.share"))
                    }
                }
                .toolbarBackground(.visible, for: .navigationBar)
        }
        .tint(Theme.Colors.onFill)
    }
}
