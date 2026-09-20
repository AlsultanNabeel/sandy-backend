//
//  SandyTasksWidget.swift — ويدجت المهام التفاعلي: أوّل تلات مهام مفتوحة، وزر ✓
//  بيكمّل المهمة من الويدجت نفسه بلا ما يفتح التطبيق.
//
//  البيانات: التطبيق بيكتب القائمة بمجموعة التطبيقات (WidgetData.setOpenTasks،
//  مفتاح `open_tasks`)، ونسخة التوكن والعنوان بيكتبها `SharedAuth` من APIClient
//  (مفاتيح `share_auth_token` و`share_base_url`). لازم المفاتيح تضل مطابقة.
//

import AppIntents
import SwiftUI
import WidgetKit

// MARK: - الكاش المشترك

private enum TaskKeys {
    static let openTasks = "open_tasks"          // SandyApp/Widgets/WidgetData.swift
    static let activeTasks = "active_tasks"
    static let lang = "app_lang"
    static let token = "share_auth_token"        // SandyApp/Core/Shared/SharedAuth.swift
    static let baseURL = "share_base_url"
    /// نفس الافتراضي بـ SandyApp/Core/Networking/Backend.swift.
    static let defaultURL = "https://sandy-robot-3da0693d32f7.herokuapp.com"
}

struct WidgetTask: Codable, Hashable, Identifiable {
    let id: String
    let text: String
    var priority: String?
}

/// قراءة/كتابة قائمة المهام المفتوحة بمجموعة التطبيقات.
private enum WidgetTaskCache {
    static var store: UserDefaults? { UserDefaults(suiteName: SandyLinks.appGroup) }

    static func load() -> [WidgetTask] {
        guard let data = store?.data(forKey: TaskKeys.openTasks),
              let rows = try? JSONDecoder().decode([WidgetTask].self, from: data) else { return [] }
        return rows
    }

    static func save(_ tasks: [WidgetTask]) {
        if let data = try? JSONEncoder().encode(tasks) {
            store?.set(data, forKey: TaskKeys.openTasks)
        }
    }

    /// يشيل المهمة (متفائلًا) ويرجّعها مع مكانها عشان نقدر نرجّعها لو فشل الخادم.
    static func remove(_ id: String) -> (task: WidgetTask, index: Int)? {
        var all = load()
        guard let i = all.firstIndex(where: { $0.id == id }) else { return nil }
        let t = all.remove(at: i)
        save(all)
        adjustCount(-1)
        return (t, i)
    }

    static func restore(_ task: WidgetTask, at index: Int) {
        var all = load()
        guard !all.contains(where: { $0.id == task.id }) else { return }
        all.insert(task, at: min(index, all.count))
        save(all)
        adjustCount(1)
    }

    /// عدّاد «المهام النشطة» بويدجت ساندي الأساسي يضل متّسق.
    private static func adjustCount(_ delta: Int) {
        let n = store?.integer(forKey: TaskKeys.activeTasks) ?? 0
        store?.set(max(0, n + delta), forKey: TaskKeys.activeTasks)
    }

    static var isArabic: Bool { store?.string(forKey: TaskKeys.lang) != "en" }

    static var token: String? {
        guard let t = store?.string(forKey: TaskKeys.token), !t.isEmpty else { return nil }
        return t
    }

    static var baseURL: String {
        let s = store?.string(forKey: TaskKeys.baseURL) ?? ""
        return s.isEmpty ? TaskKeys.defaultURL : s
    }
}

// MARK: - النيّة: كمّل مهمة

/// بتشتغل بعملية الويدجت: بتشيل المهمة من الكاش فورًا، بتبعت PATCH للخادم،
/// ولو فشل بترجّعها مكانها.
struct CompleteTaskIntent: AppIntent {
    static let title: LocalizedStringResource = "Complete task"
    static let description = IntentDescription("Marks a Sandy task as done.")
    static let isDiscoverable = false

    @Parameter(title: "Task ID")
    var taskId: String

    init() {}

    init(taskId: String) {
        self.taskId = taskId
    }

    func perform() async throws -> some IntentResult {
        guard let removed = WidgetTaskCache.remove(taskId) else { return .result() }
        WidgetCenter.shared.reloadTimelines(ofKind: SandyTasksWidget.kind)

        let ok = await Self.markDone(taskId)
        if !ok {
            WidgetTaskCache.restore(removed.task, at: removed.index)
        }
        // المهمة انقفلت من برّا التطبيق — ويدجت ساندي الأساسي يحدّث عدّاده كمان.
        WidgetCenter.shared.reloadAllTimelines()
        return .result()
    }

    /// PATCH /api/tasks/<id> {"done": true} — نفس نداء التطبيق (setTaskDone).
    private static func markDone(_ id: String) async -> Bool {
        guard let token = WidgetTaskCache.token,
              let safe = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed),
              let url = URL(string: WidgetTaskCache.baseURL + "/api/tasks/" + safe) else { return false }
        var req = URLRequest(url: url)
        req.httpMethod = "PATCH"
        req.timeoutInterval = 15
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["done": true])
        guard let (_, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse else { return false }
        return (200..<300).contains(http.statusCode)
    }
}

// MARK: - الخطّ الزمني

struct SandyTasksEntry: TimelineEntry {
    let date: Date
    let tasks: [WidgetTask]
    let total: Int
    let signedIn: Bool
    var isArabic: Bool = true
}

struct SandyTasksProvider: TimelineProvider {
    func placeholder(in context: Context) -> SandyTasksEntry {
        SandyTasksEntry(date: Date(),
                        tasks: [WidgetTask(id: "1", text: "مهمة"),
                                WidgetTask(id: "2", text: "مهمة تانية"),
                                WidgetTask(id: "3", text: "مهمة تالتة")],
                        total: 3, signedIn: true)
    }

    func getSnapshot(in context: Context, completion: @escaping (SandyTasksEntry) -> Void) {
        completion(context.isPreview ? placeholder(in: context) : current())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SandyTasksEntry>) -> Void) {
        // التطبيق بيطلب reload مع كل تغيير؛ احتياط كل ساعة.
        let next = Date().addingTimeInterval(3600)
        completion(Timeline(entries: [current()], policy: .after(next)))
    }

    private func current() -> SandyTasksEntry {
        let all = WidgetTaskCache.load()
        return SandyTasksEntry(date: Date(),
                               tasks: Array(all.prefix(3)),
                               total: all.count,
                               signedIn: WidgetTaskCache.token != nil,
                               isArabic: WidgetTaskCache.isArabic)
    }
}

// MARK: - الواجهة

struct SandyTasksWidgetView: View {
    var entry: SandyTasksEntry
    @Environment(\.widgetFamily) private var family

    private var ar: Bool { entry.isArabic }
    private var locale: Locale { Locale(identifier: ar ? "ar" : "en") }

    private func number(_ n: Int) -> String {
        let f = NumberFormatter()
        f.locale = locale
        return f.string(from: NSNumber(value: n)) ?? String(n)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            if !entry.signedIn {
                Spacer(minLength: 0)
                Text(ar ? "افتح ساندي وسجّل دخول" : "Open Sandy and sign in")
                    .font(.subheadline).foregroundStyle(.secondary)
                Spacer(minLength: 0)
            } else if entry.tasks.isEmpty {
                Spacer(minLength: 0)
                Label(ar ? "كل شي خالص" : "All done", systemImage: "checkmark.seal.fill")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.cyan)
                Spacer(minLength: 0)
            } else {
                ForEach(entry.tasks) { task in row(task) }
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .environment(\.locale, locale)
        .environment(\.layoutDirection, ar ? .rightToLeft : .leftToRight)
        .containerBackground(for: .widget) { Color.black }
    }

    private var header: some View {
        HStack(spacing: 6) {
            Image(systemName: "checklist").foregroundStyle(.cyan)
            Text(ar ? "مهامي" : "Tasks").font(.caption).bold()
            Spacer(minLength: 0)
            if entry.total > 0 {
                Text(number(entry.total))
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.black)
                    .padding(.horizontal, 6).padding(.vertical, 1)
                    .background(Capsule().fill(Color.cyan))
            }
            if family != .systemSmall {
                Link(destination: SandyLinks.quickAdd) {
                    Image(systemName: "plus.circle.fill")
                        .font(.system(size: 18))
                        .foregroundStyle(.cyan)
                }
                .accessibilityLabel(ar ? "مهمة جديدة" : "New task")
            }
        }
    }

    private func row(_ task: WidgetTask) -> some View {
        HStack(spacing: 8) {
            Button(intent: CompleteTaskIntent(taskId: task.id)) {
                Image(systemName: "circle")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(.cyan)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(ar ? "خلّصت: \(task.text)" : "Complete: \(task.text)")

            Text(task.text)
                .font(.system(size: 14, weight: .medium, design: .rounded))
                .foregroundStyle(.white)
                .lineLimit(1)
                .invalidatableContent()
            Spacer(minLength: 0)
            if task.priority == "high" {
                Circle().fill(Color.orange).frame(width: 6, height: 6)
            }
        }
    }
}

struct SandyTasksWidget: Widget {
    static let kind = "SandyTasksWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: Self.kind, provider: SandyTasksProvider()) { entry in
            SandyTasksWidgetView(entry: entry)
        }
        .configurationDisplayName("مهام ساندي")
        .description("أوّل تلات مهام — كمّلها من هون.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}
