import Foundation

// ─────────────────────────────────────────────────────────────────────────
//  RobotLive — نبض الروبوت الحي لشاشة الروبوت.
//
//  يقرأ GET /api/nodes بنفسه (مش getNodes) لأن `NodeTelemetry` ما بيحمل المزاج
//  ولا قوّة الإشارة، وهدول بالضبط اللي الشاشة الحيّة بدها. نفس الرد، قراءة أوسع.
//  التحكّم كله عبر نقاط الأجهزة القائمة: POST /api/devices/<name>/control.
// ─────────────────────────────────────────────────────────────────────────

/// لقطة حيّة من لوح ساندي — كل حقل اختياري لأن لوحًا أقدم ما بيبعث كل شي.
struct RobotLiveNode: Equatable {
    let nodeId: String
    let label: String
    let online: Bool
    let lastSeen: Date?
    let firmwareVersion: String
    /// اسم المزاج الحالي (من رقمه بالنبضة)، أو nil لو اللوح ما قاله.
    let mood: String?
    /// قوّة إشارة الدماغ بالديسيبل ملّي واط (سالب؛ أقرب للصفر أحسن).
    let rssi: Int?
    let ssid: String?
    let uptimeSec: Int?
    let volume: Int?
}

/// كتالوج جسم ساندي — بنفس أسماء الفيرموير حرفيًا (node_provision.py). احتياط
/// لما قائمة الجهاز من الخادم ما توصل؛ لو وصلت، قيمها هي المعتمدة.
enum SandyMood {
    /// بنفس ترتيب `MOOD_MAP` بالفيرموير — رقم المزاج بالنبضة هو موقعه هون.
    static let all = [
        "idle", "happy", "curious", "sad", "alert", "surprised", "big_happy",
        "focused", "bored", "excited", "love", "angry", "confused", "thinking",
        "sleepy", "shy", "proud", "worried", "playful", "calm", "grumpy",
        "hopeful", "grateful", "disappointed", "silly",
    ]
    static let gestures = ["nod", "shake", "tilt", "scan", "dance",
                           "wake", "sleep", "look_left", "look_right", "center"]
    static let melodies = ["hello", "bye", "yes", "no", "thinking", "celebrate", "notify",
                           "happy", "curious", "sad", "alert", "boot",
                           "focus_start", "focus_break", "focus_end", "error", "lowbatt"]
    static let leds = ["off", "idle", "rainbow", "breathe", "pulse", "blink", "fire",
                       "police", "party", "sunrise", "ocean", "candle", "solid",
                       "listening", "talking"]

    /// أسماء أجهزة الجسم كما يزوّدها الخادم (PART_CATALOGUE).
    enum Device {
        static let face = "sandy_face"
        static let gesture = "sandy_gesture"
        static let buzzer = "sandy_buzzer"
        static let led = "sandy_led"
    }

    static func name(at index: Int) -> String? {
        all.indices.contains(index) ? all[index] : nil
    }
}

extension APIClient {
    /// GET /api/nodes مقروءة بعمق: التليمتري كاملة (المزاج والإشارة).
    func getRobotLive() async throws -> (nodes: [RobotLiveNode], demo: Bool) {
        let r = try await request("/api/nodes")
        let rows = r["items"] as? [[String: Any]] ?? []
        let nodes: [RobotLiveNode] = rows.compactMap { row in
            guard let id = row["node_id"] as? String, !id.isEmpty else { return nil }
            let t = row["telemetry"] as? [String: Any] ?? [:]
            func int(_ k: String) -> Int? { (t[k] as? NSNumber)?.intValue }
            let moodIdx = int("mood")
            let ssid = t["ssid"] as? String
            return RobotLiveNode(
                nodeId: id,
                label: (row["label"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? id,
                online: row["online"] as? Bool ?? false,
                lastSeen: NotificationManager.parseISO(row["last_seen"] as? String ?? ""),
                firmwareVersion: row["firmware_version"] as? String ?? "",
                mood: moodIdx.flatMap { SandyMood.name(at: $0) },
                rssi: int("rssi"),
                ssid: (ssid?.isEmpty ?? true) ? nil : ssid,
                uptimeSec: int("uptime"),
                volume: int("volume"))
        }
        return (nodes, r["demo"] as? Bool ?? false)
    }
}
