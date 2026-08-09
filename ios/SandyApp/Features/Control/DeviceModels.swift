import SwiftUI


/// قيم الجهاز الجاهزة للإرسال — الشيت يبنيها ويسلّمها للستور.
struct DeviceDraft {
    let name: String           // معرّف ثابت (يُولَّد من التسمية عند الإضافة)
    let label: String
    let room: String
    let controlType: String
    let transport: DeviceTransport
    let meta: [String: Any]
}


/// أنواع التحكّم المدعومة — يطابق قيم control_type بالباك-إند. للعرض نترجم
/// التسمية عبر مفتاح l10n، لكن القيمة المُرسلة (rawValue) تبقى قانونية ثابتة.
enum ControlType: String, CaseIterable, Identifiable {
    case `switch`, dimmer, `enum`, media, cover, ir
    var id: String { rawValue }
    var labelKey: String { "control.type.\(rawValue)" }
}


/// طريقة الوصل بالواجهة — وحدة ساندي (مخرج) أو إم كيو تي تي خام.
enum TransportKind: String, CaseIterable, Identifiable {
    case node, mqtt
    var id: String { rawValue }
    var labelKey: String { rawValue == "node" ? "control.transport.node" : "control.transport.mqtt" }
}
