import Foundation

struct ChatMessage: Identifiable {
    let id = UUID()
    let role: String   // "user" | "sandy"
    // var: streaming updates the bubble's text in place.
    var text: String
    /// A line of the user's that did not go through; its bubble offers «أعد المحاولة».
    var failed = false
    /// Photos and documents sent with it, or the picture Sandy drew.
    var attachments: [ChatAttachment] = []
    /// A line of the user's: the id its send went under, so «أعد المحاولة» sends it again as
    /// the same message (the server answers a turn it already ran from its ledger).
    var clientMsgId: String?
}

/// A chat attachment kept on the server (`/api/attachments`); the bytes come by id.
struct ChatAttachment: Codable, Hashable, Identifiable {
    let id: String
    let kind: String   // "image" | "file"
    let name: String

    var isImage: Bool { kind == "image" }
}

// ── سجل المحادثات — /api/conversations ──

struct ConversationMeta: Identifiable, Codable {
    let id: String
    var title: String
    let updatedAt: String   // ISO
}

struct ConversationHit: Identifiable {
    let id: String
    let title: String
    let snippet: String
    let updatedAt: String
}

struct OnboardingData {
    var done: Bool = false
    var preferredName: String = ""
    var interests: [String] = []
    var name: String = ""
}

struct DialectOption: Identifiable {
    var id: String { key }
    let key: String
    let label: String
}

/// شخصية ساندي: لهجة + تعليمات مخصّصة (فاضية = الافتراضي).
struct PersonaData {
    var dialect: String = "palestinian"
    var customInstructions: String = ""
    var availableDialects: [DialectOption] = []
}

/// Open task as the home-screen widget stores it.
struct TaskItem: Identifiable {
    let id: String
    let text: String
    var done: Bool
    let dueAt: String       // ISO أو فاضي
    var note: String = ""    // ملاحظة اختيارية
    var priority: String = "normal"   // "low" | "normal" | "high"
}

struct ListResult<T> {
    let items: [T]
    let demo: Bool
}

// ── الفوكس + مشاهد الغرفة ──

struct FocusStatus {
    var active: Bool = false
    var label: String = ""
    var scene: String = ""
    var phase: String = "focus"     // "focus" | "break"
    var cycleIdx: Int = 1
    var cycles: Int = 1
    var focusMin: Int = 25
    var breakMin: Int = 0
    var remainingSec: Int = 0
    var totalSec: Int = 0
    var demo: Bool = false
    /// When the phase now ends, from the server's clock (`phase_ends_at_ms`).
    var phaseEndsAt: Date? = nil
    var isBreak: Bool { phase == "break" }
}

struct SceneAction: Identifiable, Equatable {
    var id = UUID()
    var device: String
    var value: String
}

struct RoomScene: Identifiable {
    let name: String
    var label: String
    var icon: String
    var actions: [SceneAction]
    var id: String { name }
}

struct FocusSession: Identifiable {
    let id = UUID()
    let label: String
    let minutes: Int
    let completed: Bool
    let startedAt: String
}

// ── البحث الخارجي — /api/research ──

struct WebResult: Identifiable {
    let id = UUID()
    let title: String
    let url: String
    let text: String
    let publishedDate: String
}

struct PlaceResult: Identifiable {
    let id = UUID()
    let name: String
    let address: String
    let rating: Double
    let reviewsCount: Int
    let phone: String
    let website: String
    let priceLevel: String
    let openNow: String
    let mapsUrl: String
}

// ── الأجهزة والوحدات — /api/devices و /api/nodes ──

/// مخرج على وحدة ساندي مربوطة — الطريقة الوحيدة اللي بيوصل فيها جهاز. جهاز انحفظ قبل
/// بموضوع MQTT خام أو عنوان ويب بيوصل بنوعه، وما بيوصله أمر (`isSupported`).
struct DeviceTransport: Equatable {
    let kind: String
    let nodeId: String
    let output: String

    var isSupported: Bool { kind == "node" }

    var asDict: [String: Any] {
        ["kind": "node", "node_id": nodeId, "output": output]
    }

    static func from(_ raw: [String: Any]) -> DeviceTransport {
        DeviceTransport(kind: raw["kind"] as? String ?? "",
                        nodeId: raw["node_id"] as? String ?? "",
                        output: raw["output"] as? String ?? "")
    }
}

/// `controlType` ∈ switch | dimmer | enum | media | cover | ir.
/// `meta` نحفظه كقاموس خام (values, min/max, buttons) ونقرأ منه بحذر.
struct DeviceItem: Identifiable {
    let name: String  // id من الباك-إند
    var label: String
    var room: String
    var controlType: String
    var transport: DeviceTransport
    var meta: [String: Any]
    var state: String
    var online: Bool
    let lastSeen: String             // ISO أو فاضي

    var id: String { name }

    var enumValues: [String] {
        (meta["values"] as? [String]) ?? []
    }
    /// One-shot values (a melody, a gesture, «take a photo», next/previous): buttons that send
    /// every tap. The server marks them (`meta.momentary`).
    var momentaryValues: [String] {
        let marked = Set((meta["momentary"] as? [String]) ?? [])
        return enumValues.filter { marked.contains($0) }
    }
    /// The remembered choices, kept as a picker.
    var choiceValues: [String] {
        let marked = Set(momentaryValues)
        return enumValues.filter { !marked.contains($0) }
    }
    var dimmerMin: Int { (meta["min"] as? NSNumber)?.intValue ?? 0 }
    var dimmerMax: Int {
        let m = (meta["max"] as? NSNumber)?.intValue ?? 100
        return m > dimmerMin ? m : 100
    }
    /// A dimmer the board takes only a number for (`meta.levels_only`): no on/off switch.
    var levelsOnly: Bool { (meta["levels_only"] as? Bool) ?? false }
    var irButtons: [String: String] {
        (meta["buttons"] as? [String: String]) ?? [:]
    }
    var irButtonNames: [String] { irButtons.keys.sorted() }

    // ── نوع text (الشاشة) ──
    var textPlaceholder: String { (meta["placeholder"] as? String) ?? "" }
    /// بالبايتات مش بالحروف: الحرف العربي بايتين ومخزن اللوح ٢٥٦ بايت.
    var textMaxBytes: Int { (meta["max_bytes"] as? NSNumber)?.intValue ?? 255 }
}

struct NodeItem: Identifiable {
    let nodeId: String
    var label: String
    let capabilities: [String]
    let outputs: [String]
    let firmwareVersion: String
    var online: Bool
    let lastSeen: String             // ISO أو فاضي
    let pairedAt: String             // ISO أو فاضي
    let telemetry: NodeTelemetry?

    var id: String { nodeId }
}

/// كلها اختيارية حتى يشتغل التطبيق مع فيرموير أقدم.
struct NodeTelemetry {
    let micLeft: Int?          // ٠..١٠٠ — المستوى اللحظي
    let micRight: Int?
    let micLeftGain: Int?      // ٠..٣٠٠ — مية يعني بلا تغيير
    let micRightGain: Int?
    let micLeftMuted: Bool?
    let micRightMuted: Bool?
    let volume: Int?           // ٠..١٠٠
    /// عنوان اللوح ع الشبكة المحلية، بيتغيّر مع الراوتر فبيجي بكل نبضة.
    let ip: String?
    /// أي لوح: `sandy-brain-s3` أو الكاميرا أو عقدة الغرفة (اللبس بينهم بيحرق لوح).
    let board: String?
    /// عنوان الكاميرا مستقل عن `ip`: اللوحين تحت معرّف واحد والبث بيروح من الكاميرا مباشرة.
    let camIP: String?
    let camBoard: String?
    /// اسم الشبكة الحالية؛ بعد التغيير بيبيّن إذا اللوح انتقل أو رجع.
    let ssid: String?
    /// شبكة الكاميرا — مستقلة زي عنوانها.
    let camSSID: String?
    /// مفتاح البث المحلي — الكاميرا بتولّده كل إقلاع والخادم بيعطيه لصاحبها بس.
    let camStreamKey: String?

    /// أول ما تسمع فيه صوت — بينفع لسؤال «هل المايكين شغّالين أصلًا؟»
    var hasMicReadings: Bool { micLeft != nil || micRight != nil }

    init?(_ dict: [String: Any]?) {
        guard let d = dict, !d.isEmpty else { return nil }
        func i(_ k: String) -> Int? { (d[k] as? NSNumber)?.intValue }
        func b(_ k: String) -> Bool? { d[k] as? Bool }
        micLeft       = i("mic_l")
        micRight      = i("mic_r")
        micLeftGain   = i("mic_l_gain")
        micRightGain  = i("mic_r_gain")
        micLeftMuted  = b("mic_l_muted")
        micRightMuted = b("mic_r_muted")
        volume        = i("volume")
        ip            = d["ip"] as? String
        board         = d["board"] as? String
        camIP         = d["cam_ip"] as? String
        camBoard      = d["cam_board"] as? String
        ssid          = d["ssid"] as? String
        camSSID       = d["cam_ssid"] as? String
        camStreamKey  = d["cam_stream_key"] as? String
    }
}

struct PairResult {
    let nodeId: String
    let already: Bool
    /// الوحدة حرّة، والربط بدّه الرمز اللي ظهر ع شاشتها (إثبات الحضور).
    var needsPresence: Bool = false
    /// الخادم قدر يوصّل الرمز للوحدة — لو لأ، غالبًا هي مطفية أو مش ع النت.
    var sent: Bool = true
}

/// التنبيه اليومي: سؤال تعارف (`question` + `qid`)، أو `agenda`، أو `none`.
struct DailyNudge {
    enum Kind: String { case question, agenda, none }
    let kind: Kind
    let qid: String     // للأسئلة فقط — نرجّعه مع الجواب
    let text: String

    var isQuestion: Bool { kind == .question }
    var hasContent: Bool { kind != .none && !text.isEmpty }
}

/// حالة الاشتراك من الباك-إند (مصدرها RevenueCat).
struct SubscriptionStatus {
    let status: String        // none | trialing | active | expired
    let plan: String
    let isSubscriber: Bool
}

enum APIErrorKind { case connection, unauthorized, server, decoding, unknown }

struct APIError: LocalizedError {
    let message: String
    /// رمز الخطأ الآلي (`error`) للتفريع بالكود؛ `message` للعرض.
    var code: String? = nil
    var kind: APIErrorKind = .unknown
    /// The HTTP status when the server answered (nil for no connection or a bad reply).
    var status: Int? = nil
    /// How long the server asked to wait before trying again (a 429's `Retry-After`).
    var retryAfter: TimeInterval? = nil
    var errorDescription: String? { message }
}

extension Error {
    /// طلب اتلغى (ريفرش انتهى أو المستخدم طلع) — مش فشل، لازم يتجاهله أي معالج خطأ.
    var isCancellation: Bool {
        self is CancellationError || (self as? URLError)?.code == .cancelled
    }
}
