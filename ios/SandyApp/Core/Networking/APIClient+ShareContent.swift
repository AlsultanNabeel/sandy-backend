import SwiftUI

extension APIClient {
    private struct ShareSuggestResponse: Decodable {
        let topic: String?
        let items: [Row]?
        struct Row: Decodable {
            let title: String?
            let url: String?
            let text: String?
        }
    }

    // GET /api/share/suggest → {"topic","items":[{title,url,text,published_date}]}
    func shareContentSuggest() async throws -> (topic: String, items: [SharedContentItem]) {
        let r: ShareSuggestResponse = try await fetch("/api/share/suggest")
        let items = (r.items ?? []).map { row in
            SharedContentItem(id: UUID().uuidString,
                              title: row.title ?? "",
                              url: row.url ?? "",
                              text: row.text ?? "")
        }
        return (r.topic ?? "", items)
    }

    private struct ShareSavedResponse: Decodable {
        let items: [Row]?
        struct Row: Decodable {
            let id: String?
            let title: String?
            let url: String?
            let text: String?
        }
    }

    // GET /api/share/saved → {"items":[{id,title,url,text,topic}]}
    func shareContentSaved() async throws -> [SharedContentItem] {
        let r: ShareSavedResponse = try await fetch("/api/share/saved")
        return (r.items ?? []).compactMap { row in
            guard let id = row.id, !id.isEmpty else { return nil }
            return SharedContentItem(id: id,
                                     title: row.title ?? "",
                                     url: row.url ?? "",
                                     text: row.text ?? "")
        }
    }

    private struct ShareSave: Encodable {
        let title: String
        let url: String
        let text: String
        let topic: String
    }

    // POST /api/share/saved {title,url,text,topic} → {"ok":true,"id"}
    func shareContentSave(item: SharedContentItem, topic: String) async throws {
        try await send("/api/share/saved", method: "POST",
                       body: ShareSave(title: item.title, url: item.url, text: item.text, topic: topic))
    }

    // DELETE /api/share/saved/<id>
    func shareContentDelete(id: String) async throws {
        try await send("/api/share/saved/\(id)", method: "DELETE")
    }
}
