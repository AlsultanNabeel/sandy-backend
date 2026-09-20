//
//  SandyWidget.swift — ويدجت ساندي: التذكير الجاي + عدد المهام النشطة.
//
//  يقرأ لقطة صغيرة كتبها التطبيق بمساحة مجموعة التطبيقات المشتركة (App Group).
//  بلا شبكة ولا توكن. التطبيق يطلب إعادة البناء فورًا عند أي تغيير.
//

import WidgetKit
import SwiftUI

private let appGroup = "group.com.sandy.app"

struct SandyEntry: TimelineEntry {
    let date: Date
    let reminderText: String?
    let reminderAt: Date?
    let activeTasks: Int
}

struct SandyProvider: TimelineProvider {
    private var store: UserDefaults? { UserDefaults(suiteName: appGroup) }

    func placeholder(in context: Context) -> SandyEntry {
        SandyEntry(date: Date(), reminderText: "تذكيرك الجاي",
                   reminderAt: Date().addingTimeInterval(3600), activeTasks: 3)
    }

    func getSnapshot(in context: Context, completion: @escaping (SandyEntry) -> Void) {
        completion(currentEntry())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SandyEntry>) -> Void) {
        // التطبيق يعمل reload فوري عند أي تغيير؛ نحدّث احتياطًا كل ساعة.
        let next = Calendar.current.date(byAdding: .hour, value: 1, to: Date())
            ?? Date().addingTimeInterval(3600)
        completion(Timeline(entries: [currentEntry()], policy: .after(next)))
    }

    private func currentEntry() -> SandyEntry {
        let text = store?.string(forKey: "next_reminder_text")
        let at = store?.double(forKey: "next_reminder_at") ?? 0
        let count = store?.integer(forKey: "active_tasks") ?? 0
        return SandyEntry(
            date: Date(),
            reminderText: (text?.isEmpty == false) ? text : nil,
            reminderAt: at > 0 ? Date(timeIntervalSince1970: at) : nil,
            activeTasks: count)
    }
}

struct SandyWidgetEntryView: View {
    var entry: SandyEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "sparkles").foregroundStyle(.cyan)
                Text("ساندي").font(.caption).bold()
                Spacer(minLength: 0)
            }
            if let reminder = entry.reminderText {
                Text(reminder).font(.headline).lineLimit(2)
                if let at = entry.reminderAt {
                    Text(at, style: .time).font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Text("ما في تذكيرات قادمة")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            Text("\(entry.activeTasks) مهام نشطة")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .containerBackground(for: .widget) { Color.black }
    }
}

struct SandyWidget: Widget {
    let kind = "SandyWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SandyProvider()) { entry in
            SandyWidgetEntryView(entry: entry)
        }
        .configurationDisplayName("ساندي")
        .description("تذكيرك الجاي ومهامك.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}
