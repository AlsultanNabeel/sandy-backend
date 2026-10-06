import AppIntents
import Foundation

// الأجهزة كيانات بتنجاب من الباك‑إند وقت التشغيل، فأي جهاز جديد بيطلع بسيري لحاله.
// التحقّق من الأمر بالباك‑إند، فما منكرّره هون.

/// المعرّف هو `name` الثابت بالباك‑إند.
struct DeviceEntity: AppEntity {
    let id: String
    let label: String
    let room: String
    let controlType: String
    let state: String

    // مُولّد بيانات النوايا بيقرأها وقت البناء، فلازم تكون نصوص حرفية.
    static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Device")

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(label)", subtitle: "\(room)")
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

struct DeviceQuery: EntityStringQuery {
    func entities(for identifiers: [DeviceEntity.ID]) async throws -> [DeviceEntity] {
        let wanted = Set(identifiers)
        return try await devices().filter { wanted.contains($0.id) }
    }

    func entities(matching string: String) async throws -> [DeviceEntity] {
        let needle = string.trimmingCharacters(in: .whitespaces).lowercased()
        guard !needle.isEmpty else { return try await devices() }
        return try await devices().filter {
            $0.label.lowercased().contains(needle)
                || $0.room.lowercased().contains(needle)
                || $0.id.lowercased().contains(needle)
        }
    }

    func suggestedEntities() async throws -> [DeviceEntity] {
        try await devices()
    }

    /// البيانات التجريبية بتنستثنى حتى ما تحاول سيري تشغّل أجهزة وهمية.
    private func devices() async throws -> [DeviceEntity] {
        let res = try await IntentAPI.make().getDevices()
        return res.demo ? [] : res.items.map(DeviceEntity.init)
    }
}

enum DeviceCommand: String, AppEnum {
    case on, off, open, close, stop, pause

    static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Command")

    static var caseDisplayRepresentations: [DeviceCommand: DisplayRepresentation] = [
        .on: DisplayRepresentation(title: "Turn on"),
        .off: DisplayRepresentation(title: "Turn off"),
        .open: DisplayRepresentation(title: "Open"),
        .close: DisplayRepresentation(title: "Close"),
        .stop: DisplayRepresentation(title: "Stop"),
        .pause: DisplayRepresentation(title: "Pause"),
    ]

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
        } catch let e as APIError where e.code == "not_sent" {
            throw SandyIntentError.notReached(device.label)
        } catch let e as APIError where e.kind == .server {
            // الباك‑إند بيرفض الأمر اللي ما بيناسب نوع الجهاز (ستارة ما بتنطفي).
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
        } catch let e as APIError where e.code == "not_sent" {
            throw SandyIntentError.notReached(device.label)
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
        } catch let e as APIError where e.code == "not_sent" {
            throw SandyIntentError.notReached(device.label)
        } catch let e as APIError where e.kind == .server {
            throw SandyIntentError.buttonNotLearned(button, device.label)
        }
        return .result(dialog: IntentAPI.dialog("بعثت \(button) لـ\(device.label)",
                                                "Sent \(button) to \(device.label)"))
    }
}
