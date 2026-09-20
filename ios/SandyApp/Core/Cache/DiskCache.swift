import Foundation

/// كاش صغير على القرص لوضع «بدون إنترنت»: ملف JSON لكل (مستخدم × ستور) تحت
/// Application Support/SandyCache/<userId>/<key>.json.
///
/// القراءة متزامنة (ملفات صغيرة، بتنقرا مرّة وحدة قبل الجلب)، والكتابة على
/// طابور تسلسلي بالخلفية. المفتاح بيتضمّن هوية المستخدم فحساب تاني على نفس
/// الجهاز ما بيشوف نسخة غيره أبدًا، و`clearAll()` بيمسح الكل عند تسجيل الخروج.
///
/// المستدعي بيمرّر `api.currentUserId` **لحظة الحفظ** (بعد الـawait): جلب كان
/// طاير وقت تسجيل الخروج بيلاقي التوكن nil فما بيكتب إشي.
enum DiskCache {
    private static let queue = DispatchQueue(label: "sandy.diskcache", qos: .utility)

    private static var root: URL? {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first?
            .appendingPathComponent("SandyCache", isDirectory: true)
    }

    /// اسم ملف آمن: حروف/أرقام و - _ . فقط.
    private static func safe(_ s: String) -> String {
        String(s.filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" || $0 == "." })
    }

    private static func fileURL(key: String, userId: String?) -> URL? {
        guard let root, let userId else { return nil }
        let uid = safe(userId)
        let name = safe(key)
        guard !uid.isEmpty, !name.isEmpty else { return nil }
        return root.appendingPathComponent(uid, isDirectory: true)
                   .appendingPathComponent(name + ".json")
    }

    /// النسخة المحفوظة (أو nil لو ما في / ما انفكّت / ما في مستخدم).
    static func load<T: Decodable>(_ type: T.Type, key: String, userId: String?) -> T? {
        guard let url = fileURL(key: key, userId: userId),
              let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(T.self, from: data)
    }

    /// يحفظ نسخة جديدة بالخلفية (كتابة ذرّية). فشل الحفظ صامت — الكاش تحسين، مش مصدر حقيقة.
    static func save<T: Encodable>(_ value: T, key: String, userId: String?) {
        guard let url = fileURL(key: key, userId: userId),
              let data = try? JSONEncoder().encode(value) else { return }
        queue.async {
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                     withIntermediateDirectories: true)
            try? data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        }
    }

    /// يمسح كل النسخ المحفوظة لكل المستخدمين — يُنادى عند تسجيل الخروج.
    /// على نفس الطابور التسلسلي، فأي حفظ سبقه بينكتب ثم بينمسح.
    static func clearAll() {
        guard let root else { return }
        queue.async { try? FileManager.default.removeItem(at: root) }
    }
}
