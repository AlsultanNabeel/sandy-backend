import SwiftUI

@MainActor
final class SearchStore: LoadableStore {
    @Published var web: [WebResult] = []
    @Published var places: [PlaceResult] = []
    /// صار في بحث واحد على الأقل (نميّز "ابدأ بالبحث" عن "ما في نتائج").
    @Published var hasSearched = false

    private var searchTask: Task<Void, Never>?

    func isEmpty(_ kind: SearchKind) -> Bool {
        kind == .web ? web.isEmpty : places.isEmpty
    }

    /// بحث مملوك للستور وينتظره — يصلح للإرسال والـ `.refreshable` معاً.
    func search(api: APIClient, q: String, kind: SearchKind) async {
        guard !q.isEmpty else { return }
        searchTask?.cancel()
        let gen = beginLoad()
        let task = Task { @MainActor in
            clearNotice()
            defer { endLoad(gen) }
            do {
                switch kind {
                case .web:
                    let r = try await api.researchWeb(q: q)
                    guard isCurrentLoad(gen) else { return }
                    web = r.items; demo = r.demo
                case .places:
                    let r = try await api.researchPlaces(q: q)
                    guard isCurrentLoad(gen) else { return }
                    places = r.items; demo = r.demo
                }
                hasSearched = true
            } catch {
                if !error.isCancellation, isCurrentLoad(gen) { notify("search.error") }
            }
        }
        searchTask = task
        await task.value
    }
}
