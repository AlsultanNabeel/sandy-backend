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

    /// جلب مملوك للستور وينتظره — يصلح للـ `.task` و`.refreshable` معاً.
    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                let r = try await api.getScenes()
                scenes = r.items
                demo = r.demo
            } catch {
                if !error.isCancellation { notice = LanguageManager.shared.s("robot.loadError") }
            }
        }
        loadTask = task
        await task.value
    }

    /// يطبّق مشهداً وينشر نتيجته (متّصل/غير متّصل/خطأ) كإشعار ودّي.
    func apply(api: APIClient, scene: RoomScene) async {
        applying = scene.name; notice = ""
        do {
            let r = try await api.applyScene(name: scene.name)
            notice = LanguageManager.shared.s(r.online ? "robot.applied" : "robot.appliedOffline")
        } catch {
            notice = LanguageManager.shared.s("robot.applyError")
        }
        applying = ""
    }

    /// إضافة مشهد جديد ثم إعادة جلب. يرجّع نجاح/فشل لتقرّر الورقة تتقفل.
    func add(api: APIClient, name: String, label: String, icon: String,
             actions: [SceneAction]) async -> Bool {
        do {
            try await api.addScene(name: name, label: label, icon: icon, actions: actions)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s(error.localizedDescription == "exists"
                                              ? "robot.nameExists" : "robot.saveError")
            return false
        }
    }

    /// تعديل أفعال مشهد قائم ثم إعادة جلب. يرجّع نجاح/فشل.
    func update(api: APIClient, scene: RoomScene, actions: [SceneAction]) async -> Bool {
        do {
            try await api.setSceneActions(name: scene.name, actions: actions)
            notice = ""
            await load(api: api)
            return true
        } catch {
            notice = LanguageManager.shared.s("robot.saveError")
            return false
        }
    }

    /// حذف مشهد ثم إعادة جلب.
    func remove(api: APIClient, scene: RoomScene) async {
        do {
            try await api.deleteScene(name: scene.name)
            await load(api: api)
        } catch {
            notice = LanguageManager.shared.s(error.localizedDescription == "builtin"
                                              ? "robot.builtinDel" : "robot.saveError")
        }
    }
}
