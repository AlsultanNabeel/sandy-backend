import SwiftUI

/// The owner's trace list, one opened turn, and the cost report (`APIClient+Owner`).
@MainActor
final class OwnerStore: LoadableStore {
    @Published var traces: [Trace] = []
    @Published var opened: Trace?
    @Published var costs: CostReport?

    func loadTraces(api: APIClient) async {
        let gen = beginLoad()
        defer { endLoad(gen) }
        clearNotice()
        do {
            let rows = try await api.ownerTraces()
            guard isCurrentLoad(gen) else { return }
            traces = rows
        } catch {
            if !error.isCancellation, isCurrentLoad(gen) { notify("developer.loadFailed") }
        }
    }

    func open(_ id: String, api: APIClient) async {
        let gen = beginLoad()
        defer { endLoad(gen) }
        clearNotice()
        do {
            let row = try await api.ownerTrace(id: id)
            guard isCurrentLoad(gen) else { return }
            opened = row
        } catch {
            if !error.isCancellation, isCurrentLoad(gen) { notify("developer.loadFailed") }
        }
    }

    func loadCosts(api: APIClient, days: Int = 30) async {
        let gen = beginLoad()
        defer { endLoad(gen) }
        clearNotice()
        do {
            let report = try await api.ownerCosts(days: days)
            guard isCurrentLoad(gen) else { return }
            costs = report
        } catch {
            if !error.isCancellation, isCurrentLoad(gen) { notify("developer.loadFailed") }
        }
    }
}
