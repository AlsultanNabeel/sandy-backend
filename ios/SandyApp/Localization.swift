import SwiftUI

// ─────────────────────────────────────────────────────────────────────────
//  Sandy localization (i18n) engine — mirrors the web app's system exactly.
//
//  WEB ORIGINAL (read-only reference, never modified):
//    frontend/src/i18n/index.js          → translate(lang, "ns.key") walks a
//                                           per-namespace table { ar:{…}, en:{…} },
//                                           falls back to ar, then to the raw key.
//    frontend/src/i18n/dict/<ns>.js       → one file per namespace, each
//                                           `export default { ar:{…}, en:{…} }`.
//    frontend/src/contexts/LanguageContext.jsx → lang ar/en persisted as
//                                           "sandy_lang"; dir = rtl/ltr; exposes
//                                           { lang, dir, t, setLang, toggle }.
//
//  iOS MAPPING:
//    • AppLang                 ↔ lang ('ar' | 'en')   (+ layoutDirection ↔ dir)
//    • LanguageManager         ↔ LanguageContext      (lang, setLang, toggle, s/list ↔ t)
//    • translate(lang, key)    ↔ translate(lang, key)
//    • L10nRegistry            ↔ DICT
//    • L10n+<Area>.swift files ↔ dict/<ns>.js files
//
//  DIFFERENCE FROM WEB: keys are FLAT within a namespace (no deep nesting).
//  Web uses "ns.a.b.c"; here a key is always exactly "namespace.key", e.g.
//  "tasks.add" → namespace "tasks", key "add". Values are String or [String].
//
//  ── USAGE PATTERN (for the per-view migration agents) ──────────────────
//    1) A View reads the manager from the environment:
//
//         @EnvironmentObject var lang: LanguageManager
//
//    2) Look up a string / a list:
//
//         Text(lang.s("tasks.add"))            // → "إضافة" / "Add"
//         ForEach(lang.list("home.tips"), …)   // → [String]
//
//    3) To ADD a string, open the namespace's `L10n+<Area>.swift` table and add
//       the key under BOTH `ar:` and `en:` (the only place strings live). The
//       registry below already lists every namespace — never edit it to add a
//       single key, only when adding a whole new namespace file.
//
//    4) Non-View code (e.g. APIClient) reads the current language via the
//       singleton: `LanguageManager.shared.lang.rawValue`.
// ─────────────────────────────────────────────────────────────────────────

// MARK: - AppLang

/// The two supported languages. Raw value matches the web ('ar' | 'en') and is
/// what the backend expects in the chat request body.
enum AppLang: String {
    case ar
    case en

    /// Drives the app-wide SwiftUI layout direction (web `dir`: rtl/ltr).
    var layoutDirection: LayoutDirection {
        switch self {
        case .ar: return .rightToLeft
        case .en: return .leftToRight
        }
    }
}

// MARK: - Translation values & tables

/// A single localized value. Mirrors the web, whose values can be a string or an
/// array of strings. We keep it to those two shapes (flat keys, no nesting).
enum L10nValue {
    case text(String)
    case items([String])
}

/// One namespace's table: the `ar` and `en` maps of flat keys → values.
/// Mirrors a web `dict/<ns>.js` `{ ar:{…}, en:{…} }`.
struct L10nTable {
    let ar: [String: L10nValue]
    let en: [String: L10nValue]

    init(ar: [String: L10nValue], en: [String: L10nValue]) {
        self.ar = ar
        self.en = en
    }

    /// The map for a given language.
    func map(for lang: AppLang) -> [String: L10nValue] {
        switch lang {
        case .ar: return ar
        case .en: return en
        }
    }
}

// MARK: - Registry (the ONLY place namespaces are listed — mirrors web DICT)

/// Assembles every namespace table by its namespace id. This is the iOS analog
/// of the web `DICT` object in i18n/index.js. Each `L10n<Area>` lives in its own
/// `L10n+<Area>.swift` file; add a new entry here only when adding a whole file.
let L10nRegistry: [String: L10nTable] = [
    L10nCommon.ns:     L10nCommon.table,
    L10nTabs.ns:       L10nTabs.table,
    L10nAuth.ns:       L10nAuth.table,
    L10nOnboarding.ns: L10nOnboarding.table,
    L10nHome.ns:       L10nHome.table,
    L10nChat.ns:       L10nChat.table,
    L10nTasks.ns:      L10nTasks.table,
    L10nReminders.ns:  L10nReminders.table,
    L10nLife.ns:       L10nLife.table,
    L10nFocus.ns:      L10nFocus.table,
    L10nRobot.ns:      L10nRobot.table,
    L10nProfile.ns:    L10nProfile.table,
]

// MARK: - translate (mirrors web translate(lang, key))

/// Split `key` on the first "." into namespace + flat key, look up the namespace
/// table, return the value for `lang`; else fall back to `.ar`; else the raw key.
/// (String lookup — for [String] use `translateList`.)
func translate(_ lang: AppLang, _ key: String) -> String {
    guard let (table, flatKey) = resolve(key) else { return key }
    if case let .text(value)? = table.map(for: lang)[flatKey] { return value }
    if case let .text(value)? = table.ar[flatKey] { return value }   // fall back to ar
    return key                                                       // fall back to raw key
}

/// Array variant of `translate`. Same lookup + fallback chain, but for [String]
/// values. Returns an empty array when nothing matches.
func translateList(_ lang: AppLang, _ key: String) -> [String] {
    guard let (table, flatKey) = resolve(key) else { return [] }
    if case let .items(value)? = table.map(for: lang)[flatKey] { return value }
    if case let .items(value)? = table.ar[flatKey] { return value }  // fall back to ar
    return []
}

/// Shared key resolver: "namespace.flatKey" → (table, flatKey).
/// Splits on the FIRST dot only, so flat keys may themselves contain dots safely.
private func resolve(_ key: String) -> (L10nTable, String)? {
    guard let dot = key.firstIndex(of: ".") else { return nil }
    let ns = String(key[key.startIndex..<dot])
    let flatKey = String(key[key.index(after: dot)...])
    guard !ns.isEmpty, !flatKey.isEmpty, let table = L10nRegistry[ns] else { return nil }
    return (table, flatKey)
}

// MARK: - LanguageManager (mirrors web LanguageContext)

/// App-wide language state. Observable so Views re-render on change, and a shared
/// singleton so non-View code (APIClient) can read the current language.
@MainActor
final class LanguageManager: ObservableObject {

    /// Shared instance — drive the whole app and let APIClient read `.lang`.
    static let shared = LanguageManager()

    /// Persisted choice (web "sandy_lang"). Default ar. We store the raw string
    /// and project it into `lang` so AppStorage and the published value stay in
    /// sync without exposing AppStorage to callers.
    @AppStorage("sandy_lang") private var storedLang: String = AppLang.ar.rawValue {
        didSet {
            let next = AppLang(rawValue: storedLang) ?? .ar
            if next != lang { lang = next }
        }
    }

    /// The current language. Read-only to callers; change via setLang/toggle.
    @Published private(set) var lang: AppLang

    private init() {
        // Initialize from the persisted value (default ar).
        let stored = UserDefaults.standard.string(forKey: "sandy_lang")
        lang = AppLang(rawValue: stored ?? AppLang.ar.rawValue) ?? .ar
    }

    /// Set the language explicitly (web setLang). Persists + publishes.
    func setLang(_ newLang: AppLang) {
        guard newLang != lang else { return }
        lang = newLang
        storedLang = newLang.rawValue
    }

    /// Flip ar ↔ en (web toggle).
    func toggle() {
        setLang(lang == .ar ? .en : .ar)
    }

    /// String lookup for the current language (web `t`).
    func s(_ key: String) -> String {
        translate(lang, key)
    }

    /// Array lookup for the current language.
    func list(_ key: String) -> [String] {
        translateList(lang, key)
    }
}

// MARK: - LanguageToggle (reusable control — Profile drops it in)

/// A small segmented control switching ar ↔ en. Mirrors the web navbar language
/// switch. Drop into any screen (e.g. ProfileView). RTL-aware via the app's
/// layout direction. Labels show each language in its own script.
struct LanguageToggle: View {
    @EnvironmentObject var lang: LanguageManager

    var body: some View {
        HStack(spacing: 0) {
            segment(title: "ع", isOn: lang.lang == .ar) { lang.setLang(.ar) }
            segment(title: "EN", isOn: lang.lang == .en) { lang.setLang(.en) }
        }
        .padding(3)
        .background(Theme.Colors.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                .stroke(Theme.Colors.border, lineWidth: 1)
        )
        .animation(.easeInOut(duration: 0.2), value: lang.lang)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(lang.s("common.language"))
    }

    @ViewBuilder
    private func segment(title: String, isOn: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(Theme.Typography.callout)
                .foregroundColor(isOn ? Theme.Colors.onAccent : Theme.Colors.accentDeep)
                .padding(.vertical, Theme.Spacing.sm)
                .padding(.horizontal, Theme.Spacing.md)
                .frame(maxWidth: .infinity)
                .background(
                    Group {
                        if isOn {
                            LinearGradient(
                                colors: [Theme.Colors.accent, Theme.Colors.accentDeep],
                                startPoint: .topLeading, endPoint: .bottomTrailing)
                        } else {
                            Color.clear
                        }
                    }
                )
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control - 3, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}
