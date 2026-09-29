import Foundation

/// مصدر واحد لعنوان الخادم حتى التطبيق وسيري ما يختلفوا.
enum Backend {
    /// مشترك بين التطبيق وإضافاته، فلازم يضل نفسه.
    static let urlDefaultsKey = "sandy_base_url"

    /// الاسم موروث من المشروع القديم؛ هو الخادم الحالي.
    static let defaultURL = "https://sandy-robot-3da0693d32f7.herokuapp.com"

    /// المحفوظ إن وُجد، وإلا الافتراضي — كمان لو المحفوظ فاضي (بيعطي طلبات بلا مضيف).
    static var currentURL: String {
        let saved = UserDefaults.standard.string(forKey: urlDefaultsKey) ?? ""
        return saved.isEmpty ? defaultURL : saved
    }
}
