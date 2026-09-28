import SwiftUI
import PhotosUI

// Goes through the shared client so a 401 signs out like everywhere else.
extension APIClient {
    func photosList(album: String? = nil) async throws -> [AlbumPhoto] {
        var path = "/api/photos"
        if let album, !album.isEmpty {
            path += "?album=\(photosEncode(album))"
        }
        let r = try await request(path)
        return (r["items"] as? [[String: Any]] ?? []).map {
            AlbumPhoto(id: $0["id"] as? String ?? "",
                       name: $0["name"] as? String ?? "",
                       caption: $0["caption"] as? String ?? "",
                       tags: $0["tags"] as? [String] ?? [],
                       createdAt: $0["created_at"] as? String ?? "")
        }
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
        _ = try await request("/api/photos/\(photosPathEscape(id))", method: "DELETE")
    }

    /// Raw image bytes. 30 s (not 15) because the album is often opened on a weak signal.
    func photosFile(id: String) async throws -> Data {
        try await rawGet("/api/photos/\(photosPathEscape(id))/file", timeout: 30)
    }

    /// Path-segment encoding: `urlQueryAllowed` would let `/` and `?` through.
    private func photosPathEscape(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? ""
    }

    private func photosEncode(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
    }
}
