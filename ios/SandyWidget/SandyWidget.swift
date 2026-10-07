// التذكيرات الجاية + عدد المهام النشطة من لقطة التطبيق بمجموعة التطبيقات (بلا شبكة ولا توكن).

import WidgetKit
import SwiftUI

private let appGroup = "group.com.sandy.app"

struct SandyEntry: TimelineEntry {
    let date: Date
    let reminderText: String?
    let reminderAt: Date?
    let activeTasks: Int
    /// افتراضيًا عربي.
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

    /// One entry per reminder's time: each shows until it rings, then the next. The app
    /// reloads the timeline whenever its reminders change.
    func getTimeline(in context: Context, completion: @escaping (Timeline<SandyEntry>) -> Void) {
        let entries = upcoming.timeline(from: Date()).map { entry(at: $0.date, ring: $0.ring) }
        completion(Timeline(entries: entries, policy: .atEnd))
    }

    private func currentEntry() -> SandyEntry {
        let now = Date()
        return entry(at: now, ring: upcoming.timeline(from: now).first?.ring)
    }

    private var upcoming: UpcomingReminders {
        guard let data = store?.data(forKey: UpcomingReminders.key),
              let up = try? JSONDecoder().decode(UpcomingReminders.self, from: data) else {
            return UpcomingReminders(rings: [])
        }
        return up
    }

    private func entry(at date: Date, ring: UpcomingReminders.Ring?) -> SandyEntry {
        SandyEntry(
            date: date,
            reminderText: ring?.text,
            reminderAt: ring?.at,
            activeTasks: store?.integer(forKey: "active_tasks") ?? 0,
            isArabic: (store?.string(forKey: "app_lang") ?? "ar") != "en")
    }
}

struct SandyWidgetEntryView: View {
    var entry: SandyEntry
    @Environment(\.widgetFamily) private var family

    /// ar → أرقام وأسماء عربية، en → إنجليزي.
    private var locale: Locale { Locale(identifier: entry.isArabic ? "ar" : "en") }

    private static let countFormatter = NumberFormatter()

    private var countText: String {
        let f = Self.countFormatter
        f.locale = locale
        return f.string(from: NSNumber(value: entry.activeTasks)) ?? String(entry.activeTasks)
    }

    private var isAccessory: Bool {
        family == .accessoryCircular || family == .accessoryRectangular || family == .accessoryInline
    }

    var body: some View {
        content
            .environment(\.locale, locale)
            .environment(\.layoutDirection, entry.isArabic ? .rightToLeft : .leftToRight)
            // نقرة خارج الأزرار تفتح الشات.
            .widgetURL(SandyLinks.chat)
            .containerBackground(for: .widget) {
                isAccessory ? Color.clear : Color.black
            }
    }

    @ViewBuilder
    private var content: some View {
        switch family {
        case .accessoryCircular:    circular
        case .accessoryRectangular: rectangular
        case .accessoryInline:      inline
        case .systemMedium:
            HStack(spacing: 12) {
                summary
                actions
            }
        default:
            summary
        }
    }

    // MARK: الشاشة الرئيسية

    private var summary: some View {
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
    }

    /// مكالمة صوتية، شات، إضافة سريعة.
    private var actions: some View {
        VStack(spacing: 6) {
            actionButton(SandyLinks.call, icon: "waveform",
                         title: entry.isArabic ? "احكي" : "Talk", prominent: true)
            actionButton(SandyLinks.chat, icon: "bubble.left.fill",
                         title: entry.isArabic ? "شات" : "Chat", prominent: false)
            actionButton(SandyLinks.quickAdd, icon: "plus",
                         title: entry.isArabic ? "إضافة" : "Add", prominent: false)
        }
        .frame(width: 104)
    }

    private func actionButton(_ url: URL, icon: String, title: String, prominent: Bool) -> some View {
        Link(destination: url) {
            HStack(spacing: 6) {
                Image(systemName: icon).font(.system(size: 13, weight: .semibold))
                Text(title).font(.system(size: 13, weight: .semibold, design: .rounded))
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            .foregroundStyle(prominent ? Color.black : Color.white)
            .padding(.horizontal, 10)
            .frame(maxWidth: .infinity, minHeight: 34)
            .background(Capsule().fill(prominent ? Color.cyan : Color.white.opacity(0.14)))
        }
    }

    // MARK: شاشة القفل

    private var circular: some View {
        ZStack {
            AccessoryWidgetBackground()
            circularGlyph
        }
    }

    private var circularGlyph: some View {
        VStack(spacing: 1) {
            Image(systemName: "sparkles").font(.system(size: 15, weight: .semibold))
            if let at = entry.reminderAt {
                Text(at, style: .time)
                    .font(.system(size: 10, weight: .semibold))
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
            }
        }
        .widgetAccentable()
        .accessibilityLabel(entry.isArabic ? "ساندي" : "Sandy")
    }

    private var rectangular: some View {
        VStack(alignment: .leading, spacing: 1) {
            HStack(spacing: 4) {
                Image(systemName: "sparkles")
                Text(entry.isArabic ? "ساندي" : "Sandy").bold()
                if let at = entry.reminderAt {
                    Spacer(minLength: 0)
                    Text(at, style: .time)
                }
            }
            .font(.caption)
            .widgetAccentable()
            Text(entry.reminderText
                 ?? (entry.isArabic ? "ما في تذكيرات قادمة" : "No upcoming reminders"))
                .font(.headline)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var inline: some View {
        if let reminder = entry.reminderText, let at = entry.reminderAt {
            Text(at, style: .time) + Text(" · " + reminder)
        } else if let reminder = entry.reminderText {
            Text(reminder)
        } else {
            Text(entry.isArabic ? "ساندي · ما في تذكيرات" : "Sandy · No reminders")
        }
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
        .supportedFamilies([.systemSmall, .systemMedium,
                            .accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}
