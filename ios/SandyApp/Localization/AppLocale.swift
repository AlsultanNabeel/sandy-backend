import Foundation

// ─────────────────────────────────────────────────────────────────────────
//  AppLocale — the ONE display locale for dates, times and numbers.
//
//  Everything the app SHOWS (dates, times, relative times, counts, amounts)
//  follows the app's chosen language (LanguageManager / "sandy_lang"), never
//  the phone's region and never a hard-coded "ar":
//    • ar → Locale "ar"  (Arabic-Indic digits ٠١٢٣, Arabic month/day names)
//    • en → Locale "en"
//
//  Parsing server dates is NOT done here — that stays locale-independent
//  (ISO8601DateFormatter / en_US_POSIX, see NotificationManager.parseISO).
//
//  Readable from any thread: the language is read straight from the same
//  UserDefaults key LanguageManager persists, so non-View code (stores,
//  notification scheduling) can use it without hopping to the main actor.
//  Formatters are cached per (language, style) — a language switch simply
//  selects a different cached formatter, so nothing stale is ever reused.
//
//  USAGE:
//    AppLocale.relative(date)                                   // "بعد ساعتين" / "in 2 hours"
//    AppLocale.dateTime(date)                                   // medium date + short time
//    AppLocale.dateTime(date, dateStyle: .medium, timeStyle: .none)
//    AppLocale.number(42)                                       // "٤٢" / "42"
//    AppLocale.number(12.5, minFraction: 0, maxFraction: 2)
//    .environment(\.locale, AppLocale.locale(for: lang.lang))   // DatePicker, Text(date, style:)
// ─────────────────────────────────────────────────────────────────────────
enum AppLocale {

    /// The app's chosen language (default ar), readable from any thread.
    static var lang: AppLang {
        AppLang(rawValue: UserDefaults.standard.string(forKey: "sandy_lang") ?? "") ?? .ar
    }

    /// True when the app language is Arabic.
    static var isArabic: Bool { lang == .ar }

    /// The display locale for a language.
    static func locale(for lang: AppLang) -> Locale {
        Locale(identifier: lang.rawValue)
    }

    /// The display locale for the current app language.
    static var current: Locale { locale(for: lang) }

    // MARK: - Formatter cache (keyed by language + style)

    private static let lock = NSLock()
    private static var cache: [String: Formatter] = [:]

    private static func cached<F: Formatter>(_ key: String, _ make: (Locale) -> F) -> F {
        let l = lang
        let fullKey = l.rawValue + "|" + key
        lock.lock()
        defer { lock.unlock() }
        if let hit = cache[fullKey] as? F { return hit }
        let made = make(locale(for: l))
        cache[fullKey] = made
        return made
    }

    // MARK: - Dates & times

    /// Relative time ("in 2 hours" / "بعد ساعتين"), full units.
    static func relative(_ date: Date, to reference: Date = Date()) -> String {
        let f: RelativeDateTimeFormatter = cached("relative") { loc in
            let x = RelativeDateTimeFormatter()
            x.locale = loc
            x.unitsStyle = .full
            return x
        }
        return f.localizedString(for: date, relativeTo: reference)
    }

    /// Date and/or time with system styles (default: medium date + short time).
    static func dateTime(_ date: Date,
                         dateStyle: DateFormatter.Style = .medium,
                         timeStyle: DateFormatter.Style = .short) -> String {
        let key = "dt|\(dateStyle.rawValue)|\(timeStyle.rawValue)"
        let f: DateFormatter = cached(key) { loc in
            let x = DateFormatter()
            x.locale = loc
            x.dateStyle = dateStyle
            x.timeStyle = timeStyle
            return x
        }
        return f.string(from: date)
    }

    // MARK: - Numbers

    /// An integer in the app language's digits. `minDigits` pads with zeros
    /// (e.g. 2 → "05" / "٠٥" for a timer); grouping only when not padded.
    static func number(_ n: Int, minDigits: Int = 1) -> String {
        let f: NumberFormatter = cached("int|\(minDigits)") { loc in
            let x = NumberFormatter()
            x.locale = loc
            x.numberStyle = .decimal
            x.maximumFractionDigits = 0
            x.minimumIntegerDigits = minDigits
            x.usesGroupingSeparator = minDigits <= 1
            return x
        }
        return f.string(from: NSNumber(value: n)) ?? String(n)
    }

    /// A decimal number in the app language's digits, with grouping.
    static func number(_ x: Double, minFraction: Int = 0, maxFraction: Int = 2) -> String {
        let f: NumberFormatter = cached("dec|\(minFraction)|\(maxFraction)") { loc in
            let nf = NumberFormatter()
            nf.locale = loc
            nf.numberStyle = .decimal
            nf.minimumFractionDigits = minFraction
            nf.maximumFractionDigits = maxFraction
            return nf
        }
        return f.string(from: NSNumber(value: x)) ?? String(x)
    }
}
