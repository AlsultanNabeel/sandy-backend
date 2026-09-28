import Foundation

struct ChatMessage: Identifiable {
    let id = UUID()
    let role: String   // "user" | "sandy"
    // var: streaming updates the bubble's text in place.
    var text: String
}

// ── سجل المحادثات — /api/conversations ──

struct ConversationMeta: Identifiable {
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

// ── الذاكرة — /api/memory ──

struct MemoryFact: Identifiable {
    let id: String
    let text: String
    let type: String
}

// ── الخط الزمني — /api/timeline ──

/// يحمل نوعه ومعرّفه ليقدر التطبيق يحذفه من مصدره.
struct TimelineEvent: Identifiable {
    let id: String
    let type: String      // task | reminder | expense | journal
    let title: String
    let subtitle: String
    let ts: String        // ISO
    var done: Bool
}

struct ProjectPlan: Identifiable {
    let id: String
    let topic: String
    let summary: String
    let finishedAt: String   // ISO
    var planText: String     // النص الكامل بصيغة Markdown — قابل للتعديل بعد المراجعة
}

struct ActiveBrainstorm {
    let topic: String
    var points: [String]
    let startedAt: String   // ISO
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

// note و priority اختياريان من الباك-إند.
struct TaskItem: Identifiable {
    let id: String
    let text: String
    var done: Bool
    let dueAt: String       // ISO أو فاضي
    var note: String = ""    // ملاحظة اختيارية
    var priority: String = "normal"   // "low" | "normal" | "high"
}

struct ReminderItem: Identifiable {
    let id: String
    let text: String
    var remindAt: String  // ISO أو فاضي
    let isRecurring: Bool
    var recurrence: String = ""   // RRULE من الخادم، مثل "RRULE:FREQ=DAILY"
    var note: String = ""
}

struct HabitItem: Identifiable {
    let id: String
    let name: String
    let streak: Int
    var doneToday: Bool
}

struct ExpenseItem: Identifiable {
    let id: String
    let amount: Double
    let note: String
    let category: String
    let at: String   // ISO أو فاضي
}

struct ExpensesSummary {
    let total: Double
    let count: Int
}

struct JournalEntry: Identifiable {
    let id: String
    let date: String
    let text: String
}

struct ListResult<T> {
    let items: [T]
    let demo: Bool
}

struct ExpensesResult {
    let items: [ExpenseItem]
    let summary: ExpensesSummary
    let demo: Bool
}

/// لقطة الرئيسية من نداءات GET الموجودة؛ كل قسم يتحمّل الفشل وحده.
struct HomeSnapshot {
    var overdueTasks: Int = 0  // due_at < الآن وغير منجزة
    var todayTasks: Int = 0
    var openTasks: Int = 0
    var sampleTaskTexts: [String] = []  // حتى 3

    var nextReminderText: String = ""
    var nextReminderAt: String = ""
    var upcomingReminders: [ReminderItem] = []  // حتى 3

    var todayExpenseTotal: Double = 0
    var weekExpenseTotal: Double = 0  // آخر 7 أيام

    var demo: Bool = false
    var hadError: Bool = false
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

/// موضوع MQTT خام، أو مخرج على وحدة ساندي مربوطة.
struct DeviceTransport: Equatable {
    let kind: String        // "mqtt" | "node"
    let topic: String       // عند mqtt
    let nodeId: String      // عند node
    let output: String      // عند node

    var asDict: [String: Any] {
        switch kind {
        case "node":
            return ["kind": "node", "node_id": nodeId, "output": output]
        default:
            return ["kind": "mqtt", "topic": topic]
        }
    }

    static func from(_ raw: [String: Any]) -> DeviceTransport {
        let kind = raw["kind"] as? String ?? "mqtt"
        return DeviceTransport(kind: kind,
                               topic: raw["topic"] as? String ?? "",
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
    var dimmerMin: Int { (meta["min"] as? NSNumber)?.intValue ?? 0 }
    var dimmerMax: Int {
        let m = (meta["max"] as? NSNumber)?.intValue ?? 100
        return m > dimmerMin ? m : 100
    }
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
    let noise: Int?            // ٠ مطفي، ١ خفيف، ٢ متوسط، ٣ قوي
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
        noise         = i("noise")
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
    var errorDescription: String? { message }
}

extension Error {
    /// طلب اتلغى (ريفرش انتهى أو المستخدم طلع) — مش فشل، لازم يتجاهله أي معالج خطأ.
    var isCancellation: Bool {
        self is CancellationError || (self as? URLError)?.code == .cancelled
    }
}
