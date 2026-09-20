import SwiftUI

/// نمط الستور المعتمد: `ObservableObject` على `@MainActor`، والجلب يجري في مهمة
/// يملكها الستور — فإلغاء إيماءة الواجهة (سحب/تنقّل) ما يلغي الجلب.
@MainActor
final class RobotStore: LoadableStore {
    @Published var scenes: [RoomScene] = []
    /// رسالة ودّية بصوت ساندي (فاضية = ما في خطأ/إشعار).
    /// اسم المشهد الجاري تطبيقه (لمؤشّر الزر داخل بطاقته).
    @Published var applying = ""

    private var loadTask: Task<Void, Never>?

    // ── الروبوت الحي ─────────────────────────────────────────────────────
    /// لوح ساندي (الدماغ) كما قالته آخر نبضة — nil = ما في روبوت مربوط.
    @Published var live: RobotLiveNode?
    /// أول جلب حي خلص (عشان نفرّق «ما في روبوت» عن «لسّا عم نجيب»).
    @Published var liveLoaded = false
    /// أجهزة الجسم المزوّدة (وش/حركات/جرس/إضاءة) بالاسم.
    @Published var parts: [String: DeviceItem] = [:]
    /// الأمر الجاري (جهاز:قيمة) — لمؤشّر الزر.
    @Published var sending = ""
    /// مزاج اخترناه للتو: بيظهر فورًا لحد ما النبضة تأكّده (أو تمرق ثماني ثواني).
    @Published private var pendingMood: (mood: String, at: Date)?

    private var pollTask: Task<Void, Never>?

    /// المزاج المعروض: المختار للتو، وإلا اللي قاله اللوح، وإلا آخر أمر محفوظ.
    var displayMood: String {
        if let p = pendingMood, Date().timeIntervalSince(p.at) < 8, live?.mood != p.mood {
            return p.mood
        }
        if let m = live?.mood { return m }
        let saved = parts[SandyMood.Device.face]?.state ?? ""
        return SandyMood.all.contains(saved) ? saved : "idle"
    }

    /// قيم جهاز من الخادم، وإلا الكتالوج الاحتياطي.
    func values(_ device: String, fallback: [String]) -> [String] {
        let v = parts[device]?.enumValues ?? []
        return v.isEmpty ? fallback : v
    }

    func has(_ device: String) -> Bool { parts[device] != nil }

    /// يبدأ نبضًا لطيفًا كل خمس ثواني وهي الشاشة ظاهرة. آمن للنداء أكتر من مرّة.
    func startLive(api: APIClient) {
        guard pollTask == nil else { return }
        pollTask = Task { @MainActor [weak self] in
            await self?.loadBody(api: api)
            while !Task.isCancelled {
                // مرجع قوي لدورة وحدة بس، فالستور بيقدر يتحرّر بين الدورات.
                guard let store = self else { return }
                await store.refreshLive(api: api)
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }

    /// يوقف النبض (اختفت الشاشة أو راح التطبيق للخلفية).
    func stopLive() {
        pollTask?.cancel()
        pollTask = nil
    }

    func refreshLive(api: APIClient) async {
        do {
            let r = try await api.getRobotLive()
            // الدماغ هو اللي إله وش؛ لو في أكتر من لوح منفضّل المتّصل.
            let pick = r.nodes.first { $0.online && $0.mood != nil }
                ?? r.nodes.first { $0.mood != nil }
                ?? r.nodes.first { $0.online }
                ?? r.nodes.first
            if live != pick { live = pick }
            if let p = pendingMood, pick?.mood == p.mood { pendingMood = nil }
            if r.demo { demo = true }
        } catch {
            // صامت: النبضة الجاية بتجرّب تاني، وخطأ كل خمس ثواني إزعاج مش معلومة.
        }
        liveLoaded = true
    }

    private func loadBody(api: APIClient) async {
        guard let r = try? await api.getDevices() else { return }
        let wanted: Set<String> = [SandyMood.Device.face, SandyMood.Device.gesture,
                                   SandyMood.Device.buzzer, SandyMood.Device.led]
        var map: [String: DeviceItem] = [:]
        for d in r.items where wanted.contains(d.name) { map[d.name] = d }
        parts = map
    }

    /// يبعت أمرًا لجهاز من أجهزة الجسم (enum: set + قيمة).
    func send(api: APIClient, device: String, value: String) async {
        sending = device + ":" + value
        clearNotice()
        if device == SandyMood.Device.face { pendingMood = (value, Date()) }
        do {
            try await api.controlDevice(name: device, action: "set", value: value)
            parts[device]?.state = value
            Haptics.play(.selection)
            if live?.online == false { notify("robot.live.sentOffline") }
        } catch {
            if device == SandyMood.Device.face { pendingMood = nil }
            Haptics.play(.failure)
            notify("robot.live.sendError")
        }
        sending = ""
    }

    /// جلب مملوك للستور وينتظره — يصلح للـ `.task` و`.refreshable` معاً.
    func load(api: APIClient) async {
        loadTask?.cancel()
        let gen = beginLoad()
        let task = Task { @MainActor in
            defer { endLoad(gen) }
            do {
                let r = try await api.getScenes()
                guard isCurrentLoad(gen) else { return }
                scenes = r.items
                demo = r.demo
            } catch {
                if !error.isCancellation, isCurrentLoad(gen) { notify("robot.loadError") }
            }
        }
        loadTask = task
        await task.value
    }

    /// يطبّق مشهداً وينشر نتيجته (متّصل/غير متّصل/خطأ) كإشعار ودّي.
    func apply(api: APIClient, scene: RoomScene) async {
        applying = scene.name; clearNotice()
        do {
            let r = try await api.applyScene(name: scene.name)
            notify(r.online ? "robot.applied" : "robot.appliedOffline")
        } catch {
            notify("robot.applyError")
        }
        applying = ""
    }

    /// إضافة مشهد جديد ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, name: String, label: String, icon: String,
             actions: [SceneAction]) async -> Bool {
        do {
            try await api.addScene(name: name, label: label, icon: icon, actions: actions)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify(error.localizedDescription == "exists"
                                              ? "robot.nameExists" : "robot.saveError")
            return false
        }
    }

    /// تعديل أفعال مشهد قائم ثم إعادة جلب. يرجّع نجاح/فشل.
    func update(api: APIClient, scene: RoomScene, actions: [SceneAction]) async -> Bool {
        do {
            try await api.setSceneActions(name: scene.name, actions: actions)
            clearNotice()
            await load(api: api)
            return true
        } catch {
            notify("robot.saveError")
            return false
        }
    }

    /// حذف مشهد ثم إعادة جلب.
    func remove(api: APIClient, scene: RoomScene) async {
        do {
            try await api.deleteScene(name: scene.name)
            await load(api: api)
        } catch {
            notify(error.localizedDescription == "builtin"
                                              ? "robot.builtinDel" : "robot.saveError")
        }
    }
}
