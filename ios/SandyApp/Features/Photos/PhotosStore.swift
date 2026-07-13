import SwiftUI
import PhotosUI

@MainActor
final class PhotosStore: LoadableStore {
    @Published var photos: [AlbumPhoto] = []
    @Published var albums: [PhotoAlbum] = []
    @Published var selectedAlbum: String?   // nil = الكل

    private var loadTask: Task<Void, Never>?

    /// يجلب الصور (مصفّاة بالألبوم المختار) + قائمة الألبومات بالتوازي.
    func load(api: APIClient) async {
        loadTask?.cancel()
        let album = selectedAlbum
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                async let photosRes = api.photosList(album: album)
                async let albumsRes = api.photosAlbums()
                photos = try await photosRes
                albums = try await albumsRes
            } catch {
                if !error.isCancellation { notify("photos.errorLoad") }
            }
        }
        loadTask = task
        await task.value
    }

    /// تصفية الألبوم تُعيد الجلب من الباك-إند (الوسم فلتر على الخادم).
    func select(album: String?, api: APIClient) {
        let next = (selectedAlbum == album) ? nil : album
        guard next != selectedAlbum else { return }
        selectedAlbum = next
        Task { await load(api: api) }
    }

    /// تصفية نصّية محلّية فوق المُحمَّل (وصف/اسم/وسوم) — بحث فوري بلا نداء.
    func visiblePhotos(matching query: String) -> [AlbumPhoto] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return photos }
        return photos.filter { p in
            let hay = ([p.name, p.caption] + p.tags).joined(separator: " ").lowercased()
            return hay.contains(q)
        }
    }

    /// إضافة صورة (JPEG) ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, image: UIImage, name: String, album: String) async -> Bool {
        guard let data = image.jpegData(compressionQuality: 0.85) else {
            notify("photos.errorAdd"); return false
        }
        do {
            try await api.photosAdd(image: data, name: name, album: album)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("photos.errorAdd")
            return false
        }
    }

    /// حذف متفائل فوري ثم مصالحة مع الباك-إند عند الفشل.
    func delete(api: APIClient, photo: AlbumPhoto) {
        guard let idx = photos.firstIndex(where: { $0.id == photo.id }) else { return }
        optimistic(
            "photos.errorDelete",
            apply: { self.photos.remove(at: idx) },
            rollback: { self.photos.insert(photo, at: min(idx, self.photos.count)) },
            call: { try await api.photosDelete(id: photo.id) }
        )
    }
}
