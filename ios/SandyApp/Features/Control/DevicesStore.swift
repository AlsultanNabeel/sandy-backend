import AppIntents
import SwiftUI

/// يملك الأجهزة + الوحدات والجلب والتحكّم والتعديلات، مستقل عن دورة حياة الشاشة.
/// الجلب بمهمة مملوكة للستور فإلغاء السحب ما يلغيه، والتحكّم متفائل ثم مصالحة.
@MainActor
final class DevicesStore: LoadableStore {
    @Published var devices: [DeviceItem] = []
    @Published var nodes: [NodeItem] = []

    private var loadTask: Task<Void, Never>?
    /// ذيل طابور أوامر التحكّم التسلسلي — كل أمر ينتظره قبل ما ينفّذ، فالأوامر
    /// المتتابعة توصل العتاد بالترتيب بلا تسابق ولا إلغاء.
    private var commandChain: Task<Void, Never>?
    /// جيل آخر ضغطة تحكّم — نصالح (نعيد الجلب) مرة وحدة بعد آخر ضغطة بالدفعة
    /// فقط، بدل إعادة جلب لكل ضغطة (كانت تسبّب عاصفة إعادات ورسائل خطأ عابرة).
    private var controlGeneration = 0

    /// تجميع الأجهزة حسب الغرفة (الفاضية تتجمّع تحت "بدون غرفة")، مرتّبة بالاسم.
    struct RoomGroup { let room: String; let devices: [DeviceItem] }
    /// أجزاء الروبوت نفسه — بيتزرعوا بأسماء ثابتة من `node_provision.PART_CATALOGUE`.
    ///
    /// السبب إنه هاد الفرز موجود: صفحة التحكّم كانت بتحطّ رقبة ساندي ووشها
    /// ومايكاتها بنفس القائمة مع لمبة الصالة والمروحة. هدول إشيان مختلفان —
    /// الأول جسمها، والتاني بيتك — والخلط بينهن بيعمل قائمة طويلة ما إلها
    /// موضوع واحد.
    ///
    /// البادئة هي المعيار لأنها هي اللي بيكتبها الخادم: `sandy_` للروبوت،
    /// و`cam_` للكاميرا. جهاز أضافه المالك بإيده ما بيبلّش فيهن، فبيضل بالبيت
    /// وين مكانه.
    static let robotPrefixes = ["sandy_", "cam_"]

    private func isRobotPart(_ device: DeviceItem) -> Bool {
        Self.robotPrefixes.contains { device.name.hasPrefix($0) }
    }

    /// أجهزة البيت وبس — بلا أجزاء الروبوت.
    var homeDevices: [DeviceItem] { devices.filter { !isRobotPart($0) } }

    /// أجزاء الروبوت وبس.
    var robotDevices: [DeviceItem] { devices.filter { isRobotPart($0) } }

    /// أجهزة البيت مجموعة حسب الغرفة. الروبوت إله صفحته.
    var roomGroups: [RoomGroup] { groups(of: homeDevices) }

    private func groups(of list: [DeviceItem]) -> [RoomGroup] {
        let grouped = Dictionary(grouping: list) { $0.room }
        return grouped
            .map { RoomGroup(room: $0.key, devices: $0.value) }
            .sorted { a, b in
                // الغرف المسمّاة أولًا (أبجديًا)، و"بدون غرفة" آخرًا.
                if a.room.isEmpty != b.room.isEmpty { return !a.room.isEmpty }
                return a.room < b.room
            }
    }

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                // نجلب الأجهزة والوحدات بالتوازي.
                async let devRes = api.getDevices()
                async let nodeRes = api.getNodes()
                let dev = try await devRes
                let nod = try await nodeRes
                devices = dev.items
                nodes = nod.items
                demo = dev.demo || nod.demo
            } catch {
                if !error.isCancellation {
                    notify("control.loadFailed")
                }
            }
        }
        loadTask = task
        await task.value
    }

    // ── التحكّم (متفائل: نعكس الحالة فورًا ثم نصالح بإعادة الجلب) ──
    // الأوامر تُنفَّذ بطابور تسلسلي (FIFO): كل ضغطة تنتظر اللي قبلها تخلص، فعشر
    // ضغطات سريعة توصل العتاد بالترتيب بلا تسابق — ولا يُلغى أي أمر.
    func control(api: APIClient, device: DeviceItem, action: String, value: String? = nil) {
        guard !demo else { return }
        // تحديث متفائل للحالة المعروضة.
        if let idx = devices.firstIndex(where: { $0.id == device.id }) {
            switch action {
            case "on", "off":     devices[idx].state = action
            case "set":           devices[idx].state = value ?? devices[idx].state
            case "open":          devices[idx].state = "open"
            case "close":         devices[idx].state = "close"
            default:              break
            }
        }
        // اربط الأمر بذيل الطابور: ينتظر السابق ثم ينفّذ. فشل أمر ما يوقف الطابور.
        controlGeneration &+= 1
        let myGeneration = controlGeneration
        let previous = commandChain
        let command = Task { @MainActor in
            await previous?.value
            do {
                try await api.controlDevice(name: device.name, action: action, value: value)
            } catch {
                if !error.isCancellation {
                    notify("control.controlFailed")
                }
            }
        }
        commandChain = command
        // مصالحة واحدة للدفعة كلها: آخر ضغطة بس تعيد الجلب بعد ما يفضى الطابور.
        Task { @MainActor in
            await command.value
            guard myGeneration == controlGeneration else { return }
            await load(api: api)
        }
    }

    // ── إضافة/تعديل/حذف جهاز ──
    func add(api: APIClient, draft: DeviceDraft) async throws {
        try await api.addDevice(name: draft.name, label: draft.label,
                                controlType: draft.controlType, transport: draft.transport,
                                room: draft.room, meta: draft.meta)
        await load(api: api)
        refreshSiriDevices()
    }

    func update(api: APIClient, device: DeviceItem, draft: DeviceDraft) async throws {
        try await api.updateDevice(name: device.name, label: draft.label, room: draft.room,
                                   controlType: draft.controlType, transport: draft.transport,
                                   meta: draft.meta)
        await load(api: api)
        refreshSiriDevices()
    }

    func delete(api: APIClient, device: DeviceItem) {
        devices.removeAll { $0.id == device.id }
        Task { @MainActor in
            do {
                try await api.deleteDevice(name: device.name)
                refreshSiriDevices()
            } catch {
                notify("control.deleteFailed")
                await load(api: api)
            }
        }
    }

    /// تنبيه سيري إنّ قائمة الأجهزة تغيّرت حتى تعيد سحبها بدل ما تضل على
    /// النسخة المخزّنة (بدونها الجهاز الجديد بيتأخّر يظهر بالأوامر الصوتية).
    private func refreshSiriDevices() {
        SandyShortcuts.updateAppShortcutParameters()
    }

    // ── الوحدات: ربط/تسمية/فكّ ──
    func pair(api: APIClient, code: String, label: String?) async throws {
        let res = try await api.pairNode(code: code, label: label)
        if res.already { notify("control.node.already") }
        await load(api: api)
    }

    func rename(api: APIClient, node: NodeItem, label: String) async throws {
        try await api.renameNode(nodeId: node.nodeId, label: label)
        await load(api: api)
    }

    func unpair(api: APIClient, node: NodeItem) {
        nodes.removeAll { $0.id == node.id }
        Task { @MainActor in
            do {
                try await api.unpairNode(nodeId: node.nodeId)
            } catch {
                notify("control.deleteFailed")
            }
            await load(api: api)
        }
    }

    // ── تعلّم زر ريموت فعليًّا: ضع الوحدة بوضع التعلّم، استفتِ آخر كود التُقط،
    //    ثم اربطه بالزر. يشتغل فقط لجهاز أشعة مربوط بوحدة. ──
    @Published var learning = false

    func learnIR(api: APIClient, device: DeviceItem, button: String) {
        let name = button.trimmingCharacters(in: .whitespaces)
        let nodeId = device.transport.nodeId
        guard !name.isEmpty else { return }
        guard !nodeId.isEmpty else {
            notify("control.ir.needNode")
            return
        }
        guard !learning else { return }
        learning = true
        Task { @MainActor in
            defer { learning = false }
            do {
                let baseline = try? await api.nodeIrLast(nodeId: nodeId)
                try await api.nodeIrLearnStart(nodeId: nodeId)
                // استفتِ حتى عشر ثوانٍ عن كود جديد (الـ at تغيّر + كود غير فاضي).
                for _ in 0..<10 {
                    try? await Task.sleep(nanoseconds: 1_000_000_000)
                    let last = try await api.nodeIrLast(nodeId: nodeId)
                    if !last.code.isEmpty && last.at != (baseline?.at ?? "") {
                        try await api.irLearn(name: device.name, button: name, code: last.code)
                        await load(api: api)
                        return
                    }
                }
                notify("control.ir.learnTimeout")
            } catch {
                notify("control.ir.learnFailed")
            }
        }
    }
}
