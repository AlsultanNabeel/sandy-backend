import AVFoundation
import SwiftUI
import UserNotifications

/// Whether the user said no to the mic or to notifications, re-read whenever the app
/// comes back to the front (they may have changed it in Settings meanwhile).
@MainActor
final class Permissions: ObservableObject {
    static let shared = Permissions()

    enum Kind { case mic, notifications }

    @Published private(set) var micDenied = false
    @Published private(set) var notificationsDenied = false

    func refresh() async {
        micDenied = AVAudioApplication.shared.recordPermission == .denied
        notificationsDenied = await UNUserNotificationCenter.current().notificationSettings()
            .authorizationStatus == .denied
    }

    func denied(_ kind: Kind) -> Bool {
        kind == .mic ? micDenied : notificationsDenied
    }

    /// The app's page in Settings (its notification page for notifications).
    static func openSettings(_ kind: Kind) {
        let link = kind == .notifications ? UIApplication.openNotificationSettingsURLString
                                          : UIApplication.openSettingsURLString
        if let url = URL(string: link) { UIApplication.shared.open(url) }
    }
}

/// A gentle «you turned this off» card with a button to the device's Settings.
/// Shows nothing while the permission is allowed.
struct PermissionCard: View {
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject private var permissions = Permissions.shared
    let kind: Permissions.Kind

    var body: some View {
        if permissions.denied(kind) {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                SandyNotice(lang.s(kind == .mic ? "permissions.micOff" : "permissions.notificationsOff"),
                            kind: .gentleWarning)
                SandyButton(title: lang.s("permissions.openSettings"), systemImage: "gearshape",
                            style: .secondary, fillWidth: true) {
                    Permissions.openSettings(kind)
                }
            }
            .transition(.opacity)
        }
    }
}
