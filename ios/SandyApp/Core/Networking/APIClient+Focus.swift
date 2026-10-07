import Foundation

extension APIClient {
    private struct FocusStatusResponse: Decodable {
        let active: Bool?
        let label: String?
        let scene: String?
        let phase: String?
        let cycle_idx: Int?
        let cycles: Int?
        let focus_min: Int?
        let break_min: Int?
        let remaining_sec: Int?
        let total_sec: Int?
        let demo: Bool?
        let phase_ends_at_ms: Double?
    }

    func getFocusStatus() async throws -> FocusStatus {
        let r: FocusStatusResponse = try await fetch("/api/life/focus")
        return FocusStatus(
            active: r.active ?? false,
            label: r.label ?? "",
            scene: r.scene ?? "",
            phase: r.phase ?? "focus",
            cycleIdx: r.cycle_idx ?? 1,
            cycles: r.cycles ?? 1,
            focusMin: r.focus_min ?? 25,
            breakMin: r.break_min ?? 0,
            remainingSec: r.remaining_sec ?? 0,
            totalSec: r.total_sec ?? 0,
            demo: r.demo ?? false,
            phaseEndsAt: r.phase_ends_at_ms.flatMap { $0 > 0 ? Date(timeIntervalSince1970: $0 / 1000) : nil })
    }

    private struct FocusStart: Encodable {
        let focus_min: Int
        let break_min: Int
        let cycles: Int
        let scene: String
        let end_scene: String
        let label: String
    }

    // (للمالك فقط)
    func startFocus(focusMin: Int, breakMin: Int, cycles: Int,
                    scene: String, endScene: String, label: String) async throws {
        try await send("/api/life/focus/start", method: "POST",
                       body: FocusStart(focus_min: focusMin, break_min: breakMin, cycles: cycles,
                                        scene: scene, end_scene: endScene, label: label))
    }

    private struct FocusStop: Encodable {
        let cancel: Bool
    }

    // (للمالك فقط)
    func stopFocus(cancel: Bool) async throws {
        try await send("/api/life/focus/stop", method: "POST", body: FocusStop(cancel: cancel))
    }

    private struct FocusHistoryResponse: Decodable {
        let sessions: [Row]?
        struct Row: Decodable {
            let label: String?
            let minutes: Int?
            let completed: Bool?
            let started_at: String?
        }
    }

    func getFocusHistory(limit: Int = 30) async throws -> [FocusSession] {
        let r: FocusHistoryResponse = try await fetch("/api/life/focus/history?limit=\(limit)")
        return (r.sessions ?? []).map { row in
            FocusSession(label: row.label ?? "",
                         minutes: row.minutes ?? 0,
                         completed: row.completed ?? false,
                         startedAt: row.started_at ?? "")
        }
    }
}
