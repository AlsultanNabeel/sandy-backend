import SwiftUI

/// يملك الأجهزة + الوحدات والجلب والتحكّم والتعديلات، مستقل عن دورة حياة الشاشة.
/// الجلب بمهمة مملوكة للستور فإلغاء السحب ما يلغيه، والتحكّم متفائل ثم مصالحة.
@MainActor
final class DevicesStore: LoadableStore {
    @Published var devices: [DeviceItem] = []
    @Published var nodes: [NodeItem] = []

    private var loadTask: Task<Void, Never>?

    /// تجميع الأجهزة حسب الغرفة (الفاضية تتجمّع تحت "بدون غرفة")، مرتّبة بالاسم.
    struct RoomGroup { let room: String; let devices: [DeviceItem] }
    var roomGroups: [RoomGroup] {
        let grouped = Dictionary(grouping: devices) { $0.room }
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
        Task { @MainActor in
            do {
                try await api.controlDevice(name: device.name, action: action, value: value)
                await load(api: api)   // مصالحة مع الحالة الحقيقية من الباك-إند
            } catch {
                if !error.isCancellation {
                    notify("control.controlFailed")
                }
                await load(api: api)
            }
        }
    }

    // ── إضافة/تعديل/حذف جهاز ──
    func add(api: APIClient, draft: DeviceDraft) async throws {
        try await api.addDevice(name: draft.name, label: draft.label,
                                controlType: draft.controlType, transport: draft.transport,
                                room: draft.room, meta: draft.meta)
        await load(api: api)
    }

    func update(api: APIClient, device: DeviceItem, draft: DeviceDraft) async throws {
        try await api.updateDevice(name: device.name, label: draft.label, room: draft.room,
                                   controlType: draft.controlType, transport: draft.transport,
                                   meta: draft.meta)
        await load(api: api)
    }

    func delete(api: APIClient, device: DeviceItem) {
        devices.removeAll { $0.id == device.id }
        Task { @MainActor in
            do {
                try await api.deleteDevice(name: device.name)
            } catch {
                notify("control.deleteFailed")
                await load(api: api)
            }
        }
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
