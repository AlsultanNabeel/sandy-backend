import SwiftUI
import PhotosUI

// Goes through the shared client so a 401 signs out like everywhere else.
extension APIClient {
    /// One page of the album, newest first, and the cursor for the page after it (nil at
    /// the end); pass that back as `before`.
    func photosList(album: String? = nil,
                    before: String? = nil) async throws -> (photos: [AlbumPhoto], next: String?) {
        var params: [String] = []
        if let album, !album.isEmpty { params.append("album=\(URLEscape.query(album))") }
        if let before { params.append("before=\(URLEscape.query(before))") }
        let path = "/api/photos" + (params.isEmpty ? "" : "?" + params.joined(separator: "&"))
        let r = try await request(path)
        let photos = (r["items"] as? [[String: Any]] ?? []).map {
            AlbumPhoto(id: $0["id"] as? String ?? "",
                       name: $0["name"] as? String ?? "",
                       caption: $0["caption"] as? String ?? "",
                       tags: $0["tags"] as? [String] ?? [],
                       createdAt: $0["created_at"] as? String ?? "")
        }
        return (photos, r["next"] as? String)
    }

    func photosAlbums() async throws -> [PhotoAlbum] {
        let r = try await request("/api/photos/albums")
        return (r["items"] as? [[String: Any]] ?? []).compactMap {
            guard let name = $0["name"] as? String, !name.isEmpty else { return nil }
            return PhotoAlbum(name: name, count: ($0["count"] as? NSNumber)?.intValue ?? 0)
        }
    }

    func photosAdd(image: Data, name: String, album: String) async throws {
        var body: [String: Any] = ["image": image.base64EncodedString()]
        if !name.isEmpty { body["name"] = name }
        if !album.isEmpty { body["album"] = album }
        // Default budget: `timeoutInterval` bounds idle time, not transfer length.
        _ = try await request("/api/photos", method: "POST", body: body)
    }

    func photosDelete(id: String) async throws {
        _ = try await request("/api/photos/\(URLEscape.segment(id))", method: "DELETE")
    }

    /// Raw image bytes. 30 s (not 15) because the album is often opened on a weak signal.
    func photosFile(id: String) async throws -> Data {
        try await rawGet("/api/photos/\(URLEscape.segment(id))/file", timeout: 30)
    }
}
