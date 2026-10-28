import Foundation

/// مصدر واحد لعنوان الخادم حتى التطبيق وسيري ما يختلفوا.
enum Backend {
    /// مشترك بين التطبيق وإضافاته، فلازم يضل نفسه.
    static let urlDefaultsKey = "sandy_base_url"

    /// الاسم موروث من المشروع القديم؛ هو الخادم الحالي.
    static let defaultURL = "https://sandy-robot-3da0693d32f7.herokuapp.com"

    /// The staging app (`docs/STAGING.md`): its Heroku address goes here once it is made.
    static let stagingURL = "https://sandy-staging.herokuapp.com"

    /// The two servers the developer screen switches between; any other address (a local
    /// run) counts as production's side, as it does on the server (`utils/env_guard.py`).
    enum Server: String, CaseIterable {
        case production, staging

        var url: String { self == .staging ? Backend.stagingURL : Backend.defaultURL }

        init(url: String) {
            let trimmed = url.hasSuffix("/") ? String(url.dropLast()) : url
            self = trimmed == Backend.stagingURL ? .staging : .production
        }
    }

    /// المحفوظ إن وُجد، وإلا الافتراضي — كمان لو المحفوظ فاضي (بيعطي طلبات بلا مضيف).
    static var currentURL: String {
        let saved = UserDefaults.standard.string(forKey: urlDefaultsKey) ?? ""
        return saved.isEmpty ? defaultURL : saved
    }
}
