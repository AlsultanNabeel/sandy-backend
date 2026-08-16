import Foundation

extension APIClient {
    /// A JSON value that may arrive as a string or a number, always surfaced as a
    /// String — mirrors the old `as? String ?? (as? NSNumber)?.stringValue` read
    /// for scene action values (the room sends brightness as "85" or 85).
    private struct FlexString: Decodable {
        let value: String
        init(from decoder: Decoder) throws {
            let c = try decoder.singleValueContainer()
            if let s = try? c.decode(String.self) { value = s }
            else if let i = try? c.decode(Int.self) { value = String(i) }
            else if let d = try? c.decode(Double.self) { value = String(d) }
            else { value = "" }
        }
    }

    private struct ScenesResponse: Decodable {
        let items: [Row]?
        let demo: Bool?
        struct Row: Decodable {
            let name: String?
            let label: String?
            let icon: String?
            let actions: [Action]?
            struct Action: Decodable {
                let device: String?
                let value: FlexString?
            }
        }
    }

    func getScenes() async throws -> ListResult<RoomScene> {
        let r: ScenesResponse = try await fetch("/api/life/scenes")
        let parsed: [RoomScene] = (r.items ?? []).compactMap { row in
            guard let name = row.name, !name.isEmpty else { return nil }
            let acts = (row.actions ?? []).map { a in
                SceneAction(device: a.device ?? "", value: a.value?.value ?? "")
            }
            return RoomScene(name: name,
                             label: row.label ?? name,
                             icon: row.icon ?? "🎛️",
                             actions: acts)
        }
        return ListResult(items: parsed, demo: r.demo ?? false)
    }

    private struct SceneName: Encodable {
        let name: String
    }

    private struct SceneActionBody: Encodable {
        let device: String
        let value: String
    }

    private struct ApplySceneResponse: Decodable {
        let ok: Bool?
        let online: Bool?
    }

    // POST /api/life/scenes/apply body {"name"} → {"ok":bool,"online":bool}
    // ok = طُبّق المشهد، online = وصل لـ room-node فعليًا.
    @discardableResult
    func applyScene(name: String) async throws -> (ok: Bool, online: Bool) {
        let r: ApplySceneResponse = try await fetch("/api/life/scenes/apply", method: "POST",
                                                    body: SceneName(name: name))
        return (r.ok ?? false, r.online ?? false)
    }

    private struct SceneCreate: Encodable {
        let name: String
        let label: String
        let icon: String
        let actions: [SceneActionBody]
    }

    // POST /api/life/scenes body {"name","label","icon","actions"} (للمالك فقط)
    func addScene(name: String, label: String, icon: String, actions: [SceneAction]) async throws {
        try await send("/api/life/scenes", method: "POST",
                       body: SceneCreate(name: name, label: label, icon: icon,
                                         actions: actions.map { SceneActionBody(device: $0.device, value: $0.value) }))
    }

    private struct SceneActionsBody: Encodable {
        let name: String
        let actions: [SceneActionBody]
    }

    // POST /api/life/scenes/actions body {"name","actions"} (للمالك فقط)
    func setSceneActions(name: String, actions: [SceneAction]) async throws {
        try await send("/api/life/scenes/actions", method: "POST",
                       body: SceneActionsBody(name: name,
                                              actions: actions.map {
                                                  SceneActionBody(device: $0.device, value: $0.value)
                                              }))
    }

    // POST /api/life/scenes/delete body {"name"} (للمالك فقط)
    func deleteScene(name: String) async throws {
        try await send("/api/life/scenes/delete", method: "POST", body: SceneName(name: name))
    }

    // MARK: - البحث الخارجي (الويب/الأماكن)

    func enc(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
    }

    private struct WebResearchResponse: Decodable {
        let items: [Row]?
        let demo: Bool?
        struct Row: Decodable {
            let title: String?
            let url: String?
            let text: String?
            let published_date: String?
        }
    }

    // GET /api/research?q=&kind=web → {"kind","items":[{title,url,text,published_date}],"demo"}
    func researchWeb(q: String) async throws -> ListResult<WebResult> {
        let r: WebResearchResponse = try await fetch("/api/research?kind=web&q=\(enc(q))")
        let items = (r.items ?? []).map { row in
            WebResult(title: row.title ?? "",
                      url: row.url ?? "",
                      text: row.text ?? "",
                      publishedDate: row.published_date ?? "")
        }
        return ListResult(items: items, demo: r.demo ?? false)
    }

    private struct PlacesResponse: Decodable {
        let items: [Row]?
        let demo: Bool?
        struct Row: Decodable {
            let name: String?
            let address: String?
            let rating: Double?
            let reviews_count: Int?
            let phone: String?
            let website: String?
            let price_level: String?
            let open_now: String?
            let maps_url: String?
        }
    }

    // GET /api/research?q=&kind=places → {"kind","items":[{name,address,rating,...}],"demo"}
    func researchPlaces(q: String) async throws -> ListResult<PlaceResult> {
        let r: PlacesResponse = try await fetch("/api/research?kind=places&q=\(enc(q))")
        let items = (r.items ?? []).map { row in
            PlaceResult(name: row.name ?? "",
                        address: row.address ?? "",
                        rating: row.rating ?? 0,
                        reviewsCount: row.reviews_count ?? 0,
                        phone: row.phone ?? "",
                        website: row.website ?? "",
                        priceLevel: row.price_level ?? "",
                        openNow: row.open_now ?? "",
                        mapsUrl: row.maps_url ?? "")
        }
        return ListResult(items: items, demo: r.demo ?? false)
    }

    // MARK: - الصور (توليد/تعديل/وصف)

    /// يفك "data:image/png;base64,XXXX" (أو base64 خام) لبايتات الصورة.
    func decodeDataURI(_ s: String) -> Data? {
        if let comma = s.range(of: ",") {
            return Data(base64Encoded: String(s[comma.upperBound...]))
        }
        return Data(base64Encoded: s)
    }

    private struct ImagePrompt: Encodable {
        let prompt: String
    }

    private struct ImageEdit: Encodable {
        let prompt: String
        let image: String
    }

    private struct ImageURLResponse: Decodable {
        let url: String?
    }

    // POST /api/image {prompt} → {url:"data:image/png;base64,..."}
    func generateImage(prompt: String) async throws -> Data {
        let r: ImageURLResponse = try await fetch("/api/image", method: "POST",
                                                  body: ImagePrompt(prompt: prompt))
        guard let url = r.url, let data = decodeDataURI(url) else {
            throw APIError(message: "تعذّر توليد الصورة")
        }
        return data
    }

    // POST /api/image/edit {prompt, image(b64)} → {url:"data:..."}
    func editImage(image: Data, prompt: String) async throws -> Data {
        let r: ImageURLResponse = try await fetch("/api/image/edit", method: "POST",
                                                  body: ImageEdit(prompt: prompt, image: image.base64EncodedString()))
        guard let url = r.url, let data = decodeDataURI(url) else {
            throw APIError(message: "تعذّر تعديل الصورة")
        }
        return data
    }

    private struct AnalyzeImage: Encodable {
        let image: String
        let question: String?
    }

    private struct ReplyResponse: Decodable {
        let reply: String?
    }

    // POST /api/analyze-image {image(b64), question} → {reply}
    func describeImage(image: Data, question: String = "") async throws -> String {
        let r: ReplyResponse = try await fetch(
            "/api/analyze-image", method: "POST",
            body: AnalyzeImage(image: image.base64EncodedString(),
                               question: question.isEmpty ? nil : question))
        return r.reply ?? ""
    }
}
