import SwiftUI
import PhotosUI

// The album used to build its own `URLRequest`s so it would not have to touch
// the shared client. That bought it a second, quieter idea of what a failure is:
// `perform` treats a 401 on an authenticated request as the session dying and
// calls `onUnauthorized` — which is what signs the user out and shows the login
// screen — and it reads the server's `message` for the human and `error` for the
// code. The album did neither. An expired session browsing photos got
// «تعذّر جلب الصورة (401)» over an empty grid and stayed signed in, on a token
// the server had already stopped accepting, until they happened to tap
// something else. Two policies for one product is how that happens; there is
// one now.
extension APIClient {
    /// GET /api/photos[?album=&q=] → {"items":[{id,name,caption,tags,created_at}]}
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

    /// GET /api/photos/albums → {"items":[{name,count}]}
    func photosAlbums() async throws -> [PhotoAlbum] {
        let r = try await request("/api/photos/albums")
        return (r["items"] as? [[String: Any]] ?? []).compactMap {
            guard let name = $0["name"] as? String, !name.isEmpty else { return nil }
            return PhotoAlbum(name: name, count: ($0["count"] as? NSNumber)?.intValue ?? 0)
        }
    }

    /// POST /api/photos {image(b64), name?, album?} → {"ok":true,"id"}
    func photosAdd(image: Data, name: String, album: String) async throws {
        var body: [String: Any] = ["image": image.base64EncodedString()]
        if !name.isEmpty { body["name"] = name }
        if !album.isEmpty { body["album"] = album }
        // The default budget, not a longer one. `timeoutInterval` bounds *idle*
        // time, not the length of the transfer (see the note on `session` in
        // APIClient.swift), so thirty seconds here means thirty seconds during
        // which an upload in progress moved no bytes at all — which is a dead
        // connection, whatever the size of the photo.
        _ = try await request("/api/photos", method: "POST", body: body)
    }

    /// DELETE /api/photos/<id> → {"ok":bool}
    func photosDelete(id: String) async throws {
        _ = try await request("/api/photos/\(photosPathEscape(id))", method: "DELETE")
    }

    /// GET /api/photos/<id>/file → raw image bytes (JPEG). صورة خام، مش JSON.
    ///
    /// Thirty seconds rather than `rawGet`'s fifteen: this is a full-size photo,
    /// and the album is the screen most likely to be opened on a weak signal.
    func photosFile(id: String) async throws -> Data {
        try await rawGet("/api/photos/\(photosPathEscape(id))/file", timeout: 30)
    }

    /// One percent-encoding for a path segment. `urlQueryAllowed` (used for the
    /// album above) lets `/` and `?` through, which is right in a query string
    /// and wrong in the middle of a path.
    private func photosPathEscape(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? ""
    }

    private func photosEncode(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
    }
}
