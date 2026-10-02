import SwiftUI

// Profile › Notifications and Profile › Support.

// MARK: - Notification preferences

/// Which notifications the user wants and their quiet hours. Kept on the phone (the
/// notifications the phone rings itself read it at once) and on the server (its pushes).
struct NotificationPrefs: Codable, Equatable {
    var reminders = true
    var daily = true
    var proactive = true
    /// "HH:MM", or "" for no quiet hours.
    var quietStart = ""
    var quietEnd = ""

    enum CodingKeys: String, CodingKey {
        case reminders, daily, proactive
        case quietStart = "quiet_start"
        case quietEnd = "quiet_end"
    }

    private static let key = "notifications.prefs"

    /// Read from any thread: the notification code runs off the main one.
    static var current: NotificationPrefs {
        guard let data = UserDefaults.standard.data(forKey: key),
              let prefs = try? JSONDecoder().decode(NotificationPrefs.self, from: data) else { return .init() }
        return prefs
    }

    func save() {
        if let data = try? JSONEncoder().encode(self) { UserDefaults.standard.set(data, forKey: Self.key) }
    }

    /// Inside the quiet hours (the window may cross midnight, e.g. 23:00–07:00).
    func isQuiet(_ date: Date) -> Bool {
        guard let start = Self.minutes(quietStart), let end = Self.minutes(quietEnd), start != end else {
            return false
        }
        let c = Calendar.current.dateComponents([.hour, .minute], from: date)
        let now = (c.hour ?? 0) * 60 + (c.minute ?? 0)
        return start < end ? (now >= start && now < end) : (now >= start || now < end)
    }

    private static func minutes(_ clock: String) -> Int? {
        let parts = clock.split(separator: ":").compactMap { Int($0) }
        return parts.count == 2 ? parts[0] * 60 + parts[1] : nil
    }
}

struct NotificationSettingsView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @State private var prefs = NotificationPrefs.current
    @State private var quiet = !NotificationPrefs.current.quietStart.isEmpty
    @State private var start = EditTimes.clock(NotificationPrefs.current.quietStart)
        ?? EditTimes.next(hour: 23)
    @State private var end = EditTimes.clock(NotificationPrefs.current.quietEnd) ?? EditTimes.next(hour: 7)

    var body: some View {
        Form {
            PermissionCard(kind: .notifications)
                .listRowBackground(Color.clear)
            Section {
                Toggle(lang.s("settings.reminders"), isOn: $prefs.reminders)
                Toggle(lang.s("settings.daily"), isOn: $prefs.daily)
                Toggle(lang.s("settings.proactive"), isOn: $prefs.proactive)
            } footer: {
                Text(lang.s("settings.kindsNote"))
            }
            Section {
                Toggle(lang.s("settings.quiet"), isOn: $quiet.animation(Animation.default.reduced))
                if quiet {
                    DatePicker(lang.s("settings.quietFrom"), selection: $start, displayedComponents: .hourAndMinute)
                    DatePicker(lang.s("settings.quietTo"), selection: $end, displayedComponents: .hourAndMinute)
                }
            } footer: {
                Text(lang.s("settings.quietNote"))
            }
        }
        .scrollContentBackground(.hidden)
        .background(SandyBackground())
        .navigationTitle(lang.s("settings.notifications"))
        .task { await load() }
        .onChange(of: prefs) { apply() }
        .onChange(of: quiet) { apply() }
        .onChange(of: start) { apply() }
        .onChange(of: end) { apply() }
    }

    /// The server's copy wins on open (another phone may have changed it).
    private func load() async {
        await Permissions.shared.refresh()
        guard let saved = try? await state.api.notificationSettings() else { return }
        prefs = saved
        quiet = !saved.quietStart.isEmpty
        if let s = EditTimes.clock(saved.quietStart) { start = s }
        if let e = EditTimes.clock(saved.quietEnd) { end = e }
    }

    private func apply() {
        var next = prefs
        next.quietStart = quiet ? EditTimes.clockText(start) : ""
        next.quietEnd = quiet ? EditTimes.clockText(end) : ""
        guard next != NotificationPrefs.current else { return }
        next.save()
        // What the phone rings follows at once; the server's pushes once it hears.
        NotificationManager.shared.preferencesChanged()
        Task { try? await state.api.saveNotificationSettings(next) }
    }
}

// MARK: - Support

struct SupportView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @State private var text = ""
    @State private var sending = false
    @State private var sent = false
    @State private var failed = ""

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        Form {
            Section {
                TextField(lang.s("settings.feedbackPlaceholder"), text: $text, axis: .vertical)
                    .lineLimit(4...10)
                Button {
                    send()
                } label: {
                    if sending { LoadingDots() } else { Text(lang.s("settings.feedbackSend")) }
                }
                .disabled(trimmed.isEmpty || sending)
            } header: {
                Text(lang.s("settings.feedbackTitle"))
            } footer: {
                Text(sent ? lang.s("settings.feedbackThanks")
                     : failed.isEmpty ? lang.s("settings.feedbackNote") : failed)
                    .foregroundColor(sent ? Theme.Colors.success : failed.isEmpty ? Theme.Colors.secondaryText
                                                                               : Theme.Colors.warn)
            }
            if let mail = mailURL {
                Section {
                    Link(destination: mail) {
                        Label(lang.s("settings.emailUs"), systemImage: "envelope")
                    }
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(SandyBackground())
        .navigationTitle(lang.s("settings.support"))
    }

    /// A mail with the version and the phone already in it; nil until the address is set.
    private var mailURL: URL? {
        guard !AppLinks.supportEmail.isEmpty else { return nil }
        var c = URLComponents()
        c.scheme = "mailto"
        c.path = AppLinks.supportEmail
        c.queryItems = [
            URLQueryItem(name: "subject", value: lang.s("settings.emailSubject")),
            URLQueryItem(name: "body", value: "\n\n— \(AppInfo.version) · \(AppInfo.device) · \(AppInfo.system)"),
        ]
        return c.url
    }

    private func send() {
        sending = true
        failed = ""
        Task {
            do {
                try await state.api.sendFeedback(text: trimmed, version: AppInfo.version,
                                                 device: AppInfo.device, system: AppInfo.system)
                text = ""
                sent = true
                Haptics.play(.success)
                Announce.say(lang.s("settings.feedbackThanks"))
            } catch {
                failed = (error as? APIError)?.message ?? lang.s("settings.feedbackFailed")
                Announce.say(failed)
            }
            sending = false
        }
    }
}
