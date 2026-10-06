import Foundation
import Network

/// Changes the server has not confirmed yet, kept on disk in the order they were made.
///
/// Every block write goes through here. With a connection it is sent at once; without
/// one it waits, the screen keeps showing the change, and the queue is sent in order
/// when the network comes back, the app returns to the front, or a screen reloads.
/// A server that answers «not now» (5xx, 408, 429) keeps the write waiting too: it is
/// tried again after a growing pause (or the one a 429 asks for), and one that keeps
/// failing (`maxTries` answers, or a day) is parked beside the queue with a notice, so it
/// neither holds the rest up nor disappears. Only a refusal (any other 4xx) drops a
/// write, and its caller is told, so the screen can undo it.
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
        /// «Not now» answers so far, and when the first came.
        var tries: Int?
        var firstFailedAt: Date?
    }

    private var ops: [Op] = []
    /// Writes that kept failing: out of the queue's way, kept on disk, queued again when
    /// the app comes back to the front or before a sign-out.
    private var parked: [Op] = []
    private var userId: String?
    private var api: APIClient?
    private var pass: Task<Void, Never>?
    /// Ops whose caller is still waiting on them, and the refusals to hand those callers.
    private var awaited: Set<UUID> = []
    private var refused: [UUID: Error] = [:]
    /// Nothing is sent before this: a backoff, or the wait a 429 asked for.
    var notBefore: Date?
    private var retry: Task<Void, Never>?
    /// The clock, so tests can age a write by a day.
    var now: () -> Date = Date.init
    private let monitor = NWPathMonitor()

    static let fileKey = "outbox"
    static let parkedKey = "outbox.parked"
    /// «Not now» answers before a write is parked, or the time since the first one.
    static let maxTries = 12
    static let maxAge: TimeInterval = 86_400
    /// The first pause after a «not now»; it doubles with each one, up to `maxPause`.
    static var firstPause: TimeInterval = 5
    static let maxPause: TimeInterval = 600

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

    /// Nothing waits in the queue (what is parked does not hold a screen's reload up).
    var isEmpty: Bool { ops.isEmpty }
    var count: Int { ops.count }
    var parkedCount: Int { parked.count }
    var refusedCount: Int { refused.count }
    /// Anything this account would lose by signing out.
    var hasUnsent: Bool { !ops.isEmpty || !parked.isEmpty }

    /// Drops this account's unsent changes: a sign-out the user chose after the warning, a
    /// deleted account, or before «reset my data» (sent after it, they would bring back
    /// rows the reset removed).
    func discard() {
        ops = []
        parked = []
        stopWaiting()
        save()
    }

    /// Queues one write and tries to send it (and anything before it). Throws only when
    /// the server refused it; offline, or told «not now», it returns and the write waits.
    func send(_ api: APIClient, _ path: String, method: String, body: (any Encodable)?) async throws {
        // No one signed in: nothing to queue it for (it must not land in an account's queue).
        guard api.currentUserId != nil else {
            throw APIError(message: "انتهت الجلسة، سجّل دخولك من جديد.", kind: .unauthorized)
        }
        bind(api)
        let op = Op(id: UUID(), method: method, path: path,
                    body: try body.map { try JSONEncoder().encode($0) })
        ops.append(op)
        save()
        awaited.insert(op.id)
        defer { awaited.remove(op.id) }
        await drain(api)
        if let error = refused.removeValue(forKey: op.id) { throw error }
    }

    /// Sends what is waiting, one at a time, in order. Stops at the first missing
    /// connection, and while a «not now» pause runs.
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

    /// The parked writes go back at the end of the queue for another round of tries, and
    /// the queue is sent (back in front, before a sign-out).
    func retryParked(_ api: APIClient) async {
        guard api.currentUserId != nil else { return }
        bind(api)
        if !parked.isEmpty {
            ops += parked.map { Op(id: $0.id, method: $0.method, path: $0.path, body: $0.body) }
            parked = []
            save()
        }
        await drain(api)
    }

    private func sendAll(_ api: APIClient) async {
        while let op = ops.first {
            if let wait = notBefore, wait > now() { return }
            do {
                try await api.sendData(op.path, method: op.method, body: op.body)
            } catch {
                if LoadableStore.isConnectionError(error) || error.isCancellation { return }
                // Signed out: keep it for when the session is back.
                if (error as? APIError)?.kind == .unauthorized { return }
                let status = (error as? APIError)?.status ?? 0
                if Self.isNotNow(status) {
                    guard ops.first?.id == op.id else { return }
                    if holdBack(wait: (error as? APIError)?.retryAfter, api) { continue }
                    return
                }
                // A delete of a row already gone (Sandy deleted it from chat) is what was asked.
                if !(op.method == "DELETE" && status == 404) { refuse(op, error) }
            }
            // Signed out or switched while it was on its way: this queue is not loaded any more.
            guard ops.first?.id == op.id else { return }
            ops.removeFirst()
            save()
        }
    }

    /// The server refused it for good. Its caller, still waiting, undoes it; one queued
    /// earlier has no caller left, so the user is told and the screens reload the server's
    /// copy.
    private func refuse(_ op: Op, _ error: Error) {
        if awaited.contains(op.id) {
            refused[op.id] = error
            return
        }
        NoticeCenter.shared.post(LanguageManager.shared.s("blocks.outboxRefused"))
        NotificationCenter.default.post(name: .sandyBlocksChanged, object: nil)
    }

    /// The server is down, restarting, slow or busy: the write is not refused.
    static func isNotNow(_ status: Int) -> Bool {
        status >= 500 || status == 408 || status == 429
    }

    /// A «not now» for the first write: it waits (the server's wait, else a pause that
    /// doubles), or, after `maxTries` or a day of them, is parked with a notice. True when
    /// it was parked, so the rest can go on.
    private func holdBack(wait asked: TimeInterval?, _ api: APIClient) -> Bool {
        var op = ops[0]
        let tries = (op.tries ?? 0) + 1
        let first = op.firstFailedAt ?? now()
        op.tries = tries
        op.firstFailedAt = first
        if tries >= Self.maxTries || now().timeIntervalSince(first) >= Self.maxAge {
            ops.removeFirst()
            parked.append(op)
            save()
            NoticeCenter.shared.post(LanguageManager.shared.s("blocks.outboxParked"))
            return true
        }
        ops[0] = op
        save()
        let pause = asked ?? min(Self.firstPause * pow(2, Double(tries - 1)), Self.maxPause)
        wait(pause, api)
        return false
    }

    /// No send for `pause`, then the queue goes again by itself.
    private func wait(_ pause: TimeInterval, _ api: APIClient) {
        notBefore = now().addingTimeInterval(pause)
        retry?.cancel()
        retry = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(pause))
            guard !Task.isCancelled, let self else { return }
            self.notBefore = nil
            await self.drain(api)
        }
    }

    /// Ends a pause (another account's queue, or a fresh round of tries).
    func stopWaiting() {
        retry?.cancel()
        retry = nil
        notBefore = nil
    }

    /// The queue belongs to one account: switching accounts loads that account's.
    private func bind(_ api: APIClient) {
        self.api = api
        let uid = api.currentUserId
        guard uid != userId else { return }
        userId = uid
        stopWaiting()
        ops = DiskCache.load([Op].self, key: Self.fileKey, userId: uid) ?? []
        parked = DiskCache.load([Op].self, key: Self.parkedKey, userId: uid) ?? []
    }

    private func save() {
        DiskCache.save(ops, key: Self.fileKey, userId: userId)
        DiskCache.save(parked, key: Self.parkedKey, userId: userId)
    }
}

/// An id made on the phone, so a row exists (and can be edited) before the server sees it.
enum ClientID {
    static func make() -> String {
        UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
    }
}
