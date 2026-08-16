import SwiftUI
import PhotosUI

/// شاشة الألبوم — صور المستخدم المحفوظة عند ساندي عبر `/api/photos`. كل صورة لها
/// وصف ووسوم ذكية (يولّدها الباك-إند بالخلفية)، والألبوم = وسم. البايتات تُجلب لكل
/// صورة من `/api/photos/<id>/file`. نمط الستور المعتمد: الجلب بمهمة يملكها الستور.
/// مفصولة تمامًا عن تيليجرام: الرفع base64 والعرض من GridFS عبر REST.
struct PhotosView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = PhotosStore()
    @State private var query = ""
    @State private var showAdd = false

    private let columns = [GridItem(.adaptive(minimum: 104), spacing: Theme.Spacing.sm)]

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                content
            }
        }
        .navigationTitle(lang.s("photos.title"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                SandyButton(title: lang.s("photos.add"),
                            systemImage: "plus.circle.fill",
                            style: .secondary) {
                    store.notice = ""
                    showAdd = true
                }
            }
        }
        .animation(.spring(response: 0.45, dampingFraction: 0.8), value: store.photos.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .fullScreenCover(isPresented: $showAdd) {
            PhotoAddSheet { image, name, album in
                await store.add(api: state.api, image: image, name: name, album: album)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if store.photos.isEmpty && !store.loading {
            emptyView
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                    Text(lang.s("photos.intro"))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .frame(maxWidth: .infinity, alignment: .leading)

                    searchField

                    if !store.albums.isEmpty { albumStrip }

                    LazyVGrid(columns: columns, spacing: Theme.Spacing.sm) {
                        ForEach(store.visiblePhotos(matching: query)) { photo in
                            photoCell(photo)
                        }
                    }
                }
                .padding(Theme.Spacing.md)
                .padding(.bottom, Theme.Spacing.xxl)
            }
        }
    }

    private var searchField: some View {
        HStack(spacing: Theme.Spacing.sm) {
            Image(systemName: "magnifyingglass")
                .foregroundColor(Theme.Colors.secondaryText)
            TextField(lang.s("photos.searchPlaceholder"), text: $query)
                .font(Theme.Typography.body)
                .textInputAutocapitalization(.never)
        }
        .padding(Theme.Spacing.sm)
        .background(RoundedRectangle(cornerRadius: Theme.Radius.control).fill(.ultraThinMaterial))
    }

    /// شريط الألبومات (الوسوم) — "الكل" + كل وسم مع عدده. يصفّي الشبكة محليًا.
    private var albumStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Theme.Spacing.sm) {
                albumChip(name: nil, label: lang.s("photos.allAlbums"))
                ForEach(store.albums) { album in
                    albumChip(name: album.name, label: "\(album.name) (\(album.count))")
                }
            }
        }
    }

    private func albumChip(name: String?, label: String) -> some View {
        let selected = store.selectedAlbum == name
        return Button {
            store.select(album: name, api: state.api)
        } label: {
            Text(label)
                .font(Theme.Typography.callout)
                .foregroundColor(selected ? Theme.Colors.onAccent : Theme.Colors.accentDeep)
                .padding(.vertical, Theme.Spacing.xs)
                .padding(.horizontal, Theme.Spacing.md)
                .background(
                    Group {
                        if selected {
                            LinearGradient(colors: [Theme.Colors.accent, Theme.Colors.accentDeep],
                                           startPoint: .topLeading, endPoint: .bottomTrailing)
                        } else {
                            Color.clear
                        }
                    }
                )
                .clipShape(Capsule())
                .overlay(Capsule().stroke(Theme.Colors.accent.opacity(selected ? 0 : 0.35), lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    private func photoCell(_ photo: AlbumPhoto) -> some View {
        PhotoThumb(photo: photo, api: state.api)
            .aspectRatio(1, contentMode: .fill)
            .frame(minWidth: 0, maxWidth: .infinity)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control))
            .contextMenu {
                Button(role: .destructive) {
                    store.delete(api: state.api, photo: photo)
                } label: { Label(lang.s("photos.delete"), systemImage: "trash") }
            }
    }

    private var emptyView: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "photo.on.rectangle.angled")
                .font(.system(size: Theme.Icon.xl))
                .foregroundColor(Theme.Colors.accent.opacity(0.5))
            Text(lang.s("photos.empty"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
            SandyButton(title: lang.s("photos.add"),
                        systemImage: "plus.circle.fill") {
                store.notice = ""
                showAdd = true
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Theme.Spacing.lg)
    }
}

// MARK: - خلية الصورة (تجلب بايتاتها بنفسها)

/// خلية مصغّرة تجلب بايتات صورتها مرّة من `/api/photos/<id>/file` وتعرضها. تُبقي
/// الجلب في مهمة تُلغى لو اختفت الخلية، وتعرض هيكلًا مؤقتًا ريثما تصل البايتات.
private struct PhotoThumb: View {
    let photo: AlbumPhoto
    let api: APIClient

    @State private var image: UIImage?

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                RoundedRectangle(cornerRadius: Theme.Radius.control)
                    .fill(.ultraThinMaterial)
                    .overlay(ProgressView().tint(Theme.Colors.accent))
            }
        }
        .task(id: photo.id) {
            if image != nil { return }
            if let data = try? await api.photosFile(id: photo.id), let img = UIImage(data: data) {
                image = img
            }
        }
    }
}

// MARK: - ورقة إضافة صورة

/// ورقة الإضافة: اختيار صورة من المكتبة + اسم/ألبوم اختياريين. تُرسل عبر closure
/// غير متزامن يرجّع نجاح/فشل لتقرّر الورقة هل تتقفل.
private struct PhotoAddSheet: View {
    let onSubmit: (_ image: UIImage, _ name: String, _ album: String) async -> Bool

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var pickedItem: PhotosPickerItem?
    @State private var image: UIImage?
    @State private var name = ""
    @State private var album = ""
    @State private var submitting = false

    var body: some View {
        SandyPopup(title: lang.s("photos.addTitle")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                PhotosPicker(selection: $pickedItem, matching: .images) {
                    Label(image == nil ? lang.s("photos.pick") : lang.s("photos.pickAgain"),
                          systemImage: "photo.on.rectangle")
                        .font(Theme.Typography.button)
                        .foregroundColor(Theme.Colors.accent)
                        .frame(maxWidth: .infinity)
                        .padding(Theme.Spacing.sm)
                        .background(RoundedRectangle(cornerRadius: Theme.Radius.control)
                            .stroke(Theme.Colors.accent.opacity(0.4), lineWidth: 1))
                }

                if let image {
                    Image(uiImage: image)
                        .resizable().scaledToFit()
                        .frame(maxHeight: 200)
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control))
                }

                field(prompt: lang.s("photos.namePrompt"),
                      placeholder: lang.s("photos.namePlaceholder"), text: $name)
                field(prompt: lang.s("photos.albumPrompt"),
                      placeholder: lang.s("photos.albumPlaceholder"), text: $album)

                SandyButton(title: lang.s("photos.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
                .disabled(image == nil)
                .opacity(image == nil ? 0.5 : 1)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
        .onChange(of: pickedItem) { _, item in loadPicked(item) }
    }

    private func field(prompt: String, placeholder: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            SectionHeader(title: prompt)
            SandyCard {
                TextField(placeholder, text: text)
                    .font(Theme.Typography.body)
            }
        }
    }

    private func loadPicked(_ item: PhotosPickerItem?) {
        guard let item else { return }
        Task {
            if let data = try? await item.loadTransferable(type: Data.self),
               let img = UIImage(data: data) {
                await MainActor.run { image = img }
            }
        }
    }

    private func save() {
        guard let img = image, !submitting else { return }
        submitting = true
        Task {
            let ok = await onSubmit(img,
                                    name.trimmingCharacters(in: .whitespacesAndNewlines),
                                    album.trimmingCharacters(in: .whitespacesAndNewlines))
            submitting = false
            if ok { dismiss() }
        }
    }
}

// MARK: - النماذج

/// صورة بالألبوم — تطابق عناصر GET /api/photos: id, name, caption, tags, created_at.
/// البايتات تُجلب على حدة من /api/photos/<id>/file عند العرض.
struct AlbumPhoto: Identifiable {
    let id: String
    let name: String
    let caption: String
    let tags: [String]
    let createdAt: String
}

/// ألبوم = وسم — تطابق عناصر GET /api/photos/albums: name, count.
struct PhotoAlbum: Identifiable {
    let name: String
    let count: Int
    var id: String { name }
}

// MARK: - الستور

// MARK: - نداءات الباك-إند (الألبوم)
