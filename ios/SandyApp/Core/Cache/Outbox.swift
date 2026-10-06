import Foundation
import Network

/// Changes the server has not confirmed yet, kept on disk in the order they were made.
///
/// Every block write goes through here. With a connection it is sent at once; without
/// one it waits, the screen keeps showing the change, and the queue is sent in order
/// when the network comes back, the app returns to the front, or a screen reloads.
/// A write the server refuses (4xx/5xx) is dropped and its caller is told, so the
/// screen can undo it; only a missing connection keeps a write waiting.
///
/// The queue is its account's, on disk: a session that ended (a 401) keeps it, and it
/// is sent only when the same account signs in again. Nothing is sent with no one signed
/// in, and another account never loads it.
@MainActor
final class Outbox {
    static let shared = Outbox()

    struct Op: Codable {
        let id: UUID
        let method: String
        let path: String
        let body: Data?
    }

    private var ops: [Op] = []
    private var userId: String?
    private var api: APIClient?
    private var pass: Task<Void, Never>?
    /// Ops the server refused, so the caller waiting on one can be told.
    private var refused: [UUID: Error] = [:]
    private let monitor = NWPathMonitor()

    private init() {
        monitor.pathUpdateHandler = { path in
            guard path.status == .satisfied else { return }
            Task { @MainActor in
                let box = Outbox.shared
                if let api = box.api { await box.drain(api) }
            }
        }
        monitor.start(queue: DispatchQueue(label: "sandy.outbox.path"))
    }

    static let fileKey = "outbox"

    var isEmpty: Bool { ops.isEmpty }
    var count: Int { ops.count }

    /// The session ended: nothing more is sent for it. `discarding` (a sign-out the user
    /// chose after the warning, or a deleted account) drops its unsent changes too; else
    /// they stay on disk for when the same account is back.
    func signedOut(discarding: Bool) {
        if discarding { DiskCache.remove(key: Self.fileKey, userId: userId) }
        ops = []
        userId = nil
    }

    /// Queues one write and tries to send it (and anything before it). Throws only when
    /// the server refused it; offline it returns and the write waits.
    func send(_ api: APIClient, _ path: String, method: String, body: (any Encodable)?) async throws {
        bind(api)
        let op = Op(id: UUID(), method: method, path: path,
                    body: try body.map { try JSONEncoder().encode($0) })
        ops.append(op)
        save()
        await drain(api)
        if let error = refused.removeValue(forKey: op.id) { throw error }
    }

    /// Sends what is waiting, one at a time, in order. Stops at the first missing connection.
    func drain(_ api: APIClient) async {
        guard api.currentUserId != nil else { return }
        bind(api)
        if let running = pass { await running.value }
        guard pass == nil, !ops.isEmpty else { return }
        let task = Task { @MainActor in await self.sendAll(api) }
        pass = task
        await task.value
        pass = nil
    }

    private func sendAll(_ api: APIClient) async {
        while let op = ops.first {
            do {
                try await api.sendData(op.path, method: op.method, body: op.body)
            } catch {
                if LoadableStore.isConnectionError(error) || error.isCancellation { return }
                // Signed out: keep it for when the session is back.
                if (error as? APIError)?.kind == .unauthorized { return }
                refused[op.id] = error
            }
            // Signed out or switched while it was on its way: this queue is not loaded any more.
            guard ops.first?.id == op.id else { return }
            ops.removeFirst()
            save()
        }
    }

    /// The queue belongs to one account: switching accounts loads that account's.
    private func bind(_ api: APIClient) {
        self.api = api
        let uid = api.currentUserId
        guard uid != userId else { return }
        userId = uid
        ops = DiskCache.load([Op].self, key: Self.fileKey, userId: uid) ?? []
    }

    private func save() {
        DiskCache.save(ops, key: Self.fileKey, userId: userId)
    }
}

/// An id made on the phone, so a row exists (and can be edited) before the server sees it.
enum ClientID {
    static func make() -> String {
        UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
    }
}
