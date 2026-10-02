import Foundation

// Namespace: permissions — the cards shown where a denied mic or notifications is needed.
enum L10nPermissions {
    static let ns = "permissions"

    static let table = L10nTable(
        ar: [
            "title": .text("الأذونات"),
            "mic": .text("المايك"),
            "notifications": .text("الإشعارات"),
            "allowed": .text("مسموح"),
            "off": .text("مسكّر"),
            "micOff": .text("المايك مسكّر عن ساندي، فما بقدر أسمعك. افتحه من الإعدادات وبنحكي 🤍"),
            "notificationsOff": .text("الإشعارات مسكّرة، فتذكيراتي ما رح توصلك. افتحها من الإعدادات 🔔"),
            "openSettings": .text("افتح الإعدادات"),
        ],
        en: [
            "title": .text("Permissions"),
            "mic": .text("Microphone"),
            "notifications": .text("Notifications"),
            "allowed": .text("Allowed"),
            "off": .text("Off"),
            "micOff": .text("The microphone is off for Sandy, so I can't hear you. Turn it on in Settings and let's talk 🤍"),
            "notificationsOff": .text("Notifications are off, so my reminders won't reach you. Turn them on in Settings 🔔"),
            "openSettings": .text("Open Settings"),
        ]
    )
}
