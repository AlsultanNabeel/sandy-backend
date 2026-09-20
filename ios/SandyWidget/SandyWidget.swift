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
    /// لغة التطبيق كما كتبها التطبيق بالمساحة المشتركة (افتراضيًا عربي).
    var isArabic: Bool = true
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
        let lang = store?.string(forKey: "app_lang") ?? "ar"
        return SandyEntry(
            date: Date(),
            reminderText: (text?.isEmpty == false) ? text : nil,
            reminderAt: at > 0 ? Date(timeIntervalSince1970: at) : nil,
            activeTasks: count,
            isArabic: lang != "en")
    }
}

struct SandyWidgetEntryView: View {
    var entry: SandyEntry

    /// نفس لغة التطبيق: ar → أرقام عربية وأسماء عربية، en → إنجليزي.
    private var locale: Locale { Locale(identifier: entry.isArabic ? "ar" : "en") }

    private static let countFormatter = NumberFormatter()

    private var countText: String {
        let f = Self.countFormatter
        f.locale = locale
        return f.string(from: NSNumber(value: entry.activeTasks)) ?? String(entry.activeTasks)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "sparkles").foregroundStyle(.cyan)
                Text(entry.isArabic ? "ساندي" : "Sandy").font(.caption).bold()
                Spacer(minLength: 0)
            }
            if let reminder = entry.reminderText {
                Text(reminder).font(.headline).lineLimit(2)
                if let at = entry.reminderAt {
                    Text(at, style: .time).font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Text(entry.isArabic ? "ما في تذكيرات قادمة" : "No upcoming reminders")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            Text(entry.isArabic ? "\(countText) مهام نشطة" : "\(countText) active tasks")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .environment(\.locale, locale)
        .environment(\.layoutDirection, entry.isArabic ? .rightToLeft : .leftToRight)
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
