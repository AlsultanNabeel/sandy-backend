import Foundation

/// The language the widgets speak: the app's (`app_lang` in the shared group, written by the
/// app); before the app has said, the phone's, as the app itself starts.
enum WidgetLanguage {
    static var isArabic: Bool {
        if let saved = UserDefaults(suiteName: SandyLinks.appGroup)?.string(forKey: "app_lang") { return saved != "en" }
        // The first of the phone's languages the app speaks, as `AppLang.initial` reads it.
        let spoken = Locale.preferredLanguages.first { $0.hasPrefix("ar") || $0.hasPrefix("en") }
        return spoken?.hasPrefix("ar") ?? false
    }
}
