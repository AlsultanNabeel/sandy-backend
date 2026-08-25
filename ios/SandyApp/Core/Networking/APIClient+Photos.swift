import SwiftUI
import PhotosUI

extension APIClient {
    /// GET /api/photos[?album=&q=] → {"items":[{id,name,caption,tags,created_at}]}
    func photosList(album: String? = nil) async throws -> [AlbumPhoto] {
        var path = "/api/photos"
        if let album, !album.isEmpty {
            path += "?album=\(photosEncode(album))"
        }
        let r = try await photosRequest(path)
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
        let r = try await photosRequest("/api/photos/albums")
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
        _ = try await photosRequest("/api/photos", method: "POST", body: body)
    }

    /// DELETE /api/photos/<id> → {"ok":bool}
    func photosDelete(id: String) async throws {
        _ = try await photosRequest("/api/photos/\(id)", method: "DELETE")
    }

    /// GET /api/photos/<id>/file → raw image bytes (JPEG). صورة خام، مش JSON.
    func photosFile(id: String) async throws -> Data {
        guard let url = URL(string: baseURL + "/api/photos/\(id)/file") else {
            throw APIError(message: "عنوان غير صالح")
        }
        var req = URLRequest(url: url)
        if let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        // Through the retry, not straight at the session: this is a GET for a
        // JPEG on cellular, the exact request the retry exists for.
        let (data, resp) = try await APIClient.sendWithRetry(req, method: "GET")
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code >= 400 { throw APIError(message: "تعذّر جلب الصورة (\(code))") }
        return data
    }

    /// نسخة JSON من نداء الباك-إند خاصة بالألبوم (نفس عقد `request`) — معرّفة هون
    /// حتى تبقى نداءات الألبوم مكتفية بملفها بدون تعديل ملف APIClient المشترك.
    private func photosRequest(_ path: String,
                               method: String = "GET",
                               body: [String: Any]? = nil) async throws -> [String: Any] {
        guard let url = URL(string: baseURL + path) else { throw APIError(message: "عنوان غير صالح") }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        if let body { req.httpBody = try JSONSerialization.data(withJSONObject: body) }
        let (data, resp) = try await APIClient.sendWithRetry(req, method: method)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        if code >= 400 { throw APIError(message: (json["error"] as? String) ?? "خطأ \(code)") }
        return json
    }

    private func photosEncode(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
    }
}
