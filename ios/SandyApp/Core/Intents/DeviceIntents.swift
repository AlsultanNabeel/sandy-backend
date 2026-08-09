import AppIntents
import Foundation

// ─────────────────────────────────────────────────────────────────────────
//  DeviceIntents — التحكّم بأجهزة البيت من سيري وتطبيق الاختصارات.
//
//  الجهاز هون "كيان" (AppEntity) مش نص مكتوب بالكود: الاستعلام بيجيب أجهزة
//  الحساب من الباك‑إند وقت التشغيل، فأي جهاز بتضيفه من شاشة التحكّم بيطلع
//  لحاله بسيري وبالاختصارات وبسبوتلايت بدون ما نلمس الكود.
//
//  المسارات المستعملة: GET /api/devices للقائمة، و
//  POST /api/devices/<name>/control للأمر. التحقّق من الأمر (شو مسموح لكل نوع)
//  بيصير بالباك‑إند، فما منكرّره هون.
// ─────────────────────────────────────────────────────────────────────────

/// جهاز واحد كما يشوفه سيري — المعرّف هو `name` الثابت بالباك‑إند.
struct DeviceEntity: AppEntity {
    let id: String
    let label: String
    let room: String
    let controlType: String
    let state: String

    static var typeDisplayRepresentation: TypeDisplayRepresentation {
        TypeDisplayRepresentation(name: IntentAPI.say("جهاز", "Device"))
    }

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(label)",
                              subtitle: room.isEmpty ? nil : "\(room)")
    }

    static var defaultQuery = DeviceQuery()

    init(_ item: DeviceItem) {
        id = item.name
        label = item.label.isEmpty ? item.name : item.label
        room = item.room
        controlType = item.controlType
        state = item.state
    }
}

/// مصدر الأجهزة لسيري: اقتراحات + بحث بالاسم المنطوق + استرجاع بالمعرّف.
struct DeviceQuery: EntityStringQuery {
    /// استرجاع بالمعرّف — لما يكون الاختصار محفوظ بجهاز مختار مسبقاً.
    func entities(for identifiers: [DeviceEntity.ID]) async throws -> [DeviceEntity] {
        let wanted = Set(identifiers)
        return try await devices().filter { wanted.contains($0.id) }
    }

    /// مطابقة الاسم المنطوق — بنطابق على التسمية والغرفة والمعرّف.
    func entities(matching string: String) async throws -> [DeviceEntity] {
        let needle = string.trimmingCharacters(in: .whitespaces).lowercased()
        guard !needle.isEmpty else { return try await devices() }
        return try await devices().filter {
            $0.label.lowercased().contains(needle)
                || $0.room.lowercased().contains(needle)
                || $0.id.lowercased().contains(needle)
        }
    }

    /// القائمة اللي بتظهر بتطبيق الاختصارات لما تختار الجهاز يدوياً.
    func suggestedEntities() async throws -> [DeviceEntity] {
        try await devices()
    }

    /// أجهزة الحساب الحالي. البيانات التجريبية بتنستثنى — ما بدنا سيري تسمّي
    /// أجهزة وهمية ولا تحاول تشغّلها.
    private func devices() async throws -> [DeviceEntity] {
        let res = try await IntentAPI.make().getDevices()
        return res.demo ? [] : res.items.map(DeviceEntity.init)
    }
}

/// الأوامر اللي بيفهمها الباك‑إند: تشغيل/إطفاء للمفاتيح والإضاءة والوسائط،
/// وفتح/إغلاق/إيقاف للستائر، وتعليق للوسائط.
enum DeviceCommand: String, AppEnum {
    case on, off, open, close, stop, pause

    static var typeDisplayRepresentation: TypeDisplayRepresentation {
        TypeDisplayRepresentation(name: IntentAPI.say("أمر", "Command"))
    }

    static var caseDisplayRepresentations: [DeviceCommand: DisplayRepresentation] = [
        .on: DisplayRepresentation(title: IntentAPI.say("شغّل", "Turn on")),
        .off: DisplayRepresentation(title: IntentAPI.say("طفّي", "Turn off")),
        .open: DisplayRepresentation(title: IntentAPI.say("افتح", "Open")),
        .close: DisplayRepresentation(title: IntentAPI.say("سكّر", "Close")),
        .stop: DisplayRepresentation(title: IntentAPI.say("وقّف", "Stop")),
        .pause: DisplayRepresentation(title: IntentAPI.say("علّق", "Pause")),
    ]

    /// جملة التأكيد اللي سيري بتقولها بعد ما ينفّذ الأمر.
    func doneDialog(_ label: String) -> IntentDialog {
        switch self {
        case .on:    return IntentAPI.dialog("شغّلت \(label)", "Turned on \(label)")
        case .off:   return IntentAPI.dialog("طفّيت \(label)", "Turned off \(label)")
        case .open:  return IntentAPI.dialog("فتحت \(label)", "Opened \(label)")
        case .close: return IntentAPI.dialog("سكّرت \(label)", "Closed \(label)")
        case .stop:  return IntentAPI.dialog("وقّفت \(label)", "Stopped \(label)")
        case .pause: return IntentAPI.dialog("علّقت \(label)", "Paused \(label)")
        }
    }
}

// MARK: - النوايا

struct ControlDeviceIntent: AppIntent {
    static var title: LocalizedStringResource = "Control Device"
    static var description = IntentDescription("Turn a Sandy device on or off, or open and close it.")

    @Parameter(title: "Device") var device: DeviceEntity
    @Parameter(title: "Command", default: .on) var command: DeviceCommand

    init() {}

    /// تُستعمل بمزوّد الاختصارات لتثبيت الأمر بالعبارة (شغّل/طفّي/افتح/سكّر).
    init(command: DeviceCommand) {
        self.command = command
    }

    static var parameterSummary: some ParameterSummary {
        Summary("\(\.$command) \(\.$device)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        do {
            try await api.controlDevice(name: device.id, action: command.rawValue)
        } catch let e as APIError where e.kind == .server {
            // الباك‑إند بيرفض الأمر اللي ما بيناسب نوع الجهاز (ستارة ما بتنطفي).
            // أخطاء الشبكة والجلسة بتطلع برسالتها الأصلية.
            throw SandyIntentError.commandNotSupported(device.label)
        }
        return .result(dialog: command.doneDialog(device.label))
    }
}

struct SetDeviceLevelIntent: AppIntent {
    static var title: LocalizedStringResource = "Set Device Level"
    static var description = IntentDescription("Set the brightness or level of a dimmable Sandy device.")

    @Parameter(title: "Device") var device: DeviceEntity
    @Parameter(title: "Level", default: 50, inclusiveRange: (0, 100)) var level: Int

    static var parameterSummary: some ParameterSummary {
        Summary("Set \(\.$device) to \(\.$level)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        do {
            try await api.controlDevice(name: device.id, action: "set", value: String(level))
        } catch let e as APIError where e.kind == .server {
            throw SandyIntentError.commandNotSupported(device.label)
        }
        return .result(dialog: IntentAPI.dialog("خلّيت \(device.label) على \(level)",
                                                "Set \(device.label) to \(level)"))
    }
}

struct PressDeviceButtonIntent: AppIntent {
    static var title: LocalizedStringResource = "Press Remote Button"
    static var description = IntentDescription("Send a learned remote button to an infrared Sandy device.")

    @Parameter(title: "Device") var device: DeviceEntity
    @Parameter(title: "Button") var button: String

    static var parameterSummary: some ParameterSummary {
        Summary("Press \(\.$button) on \(\.$device)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let api = try IntentAPI.make()
        do {
            try await api.controlDevice(name: device.id, action: "send", value: button)
        } catch let e as APIError where e.kind == .server {
            // زر مش متعلَّم بعد، أو الجهاز مش ريموت.
            throw SandyIntentError.buttonNotLearned(button, device.label)
        }
        return .result(dialog: IntentAPI.dialog("بعثت \(button) لـ\(device.label)",
                                                "Sent \(button) to \(device.label)"))
    }
}
