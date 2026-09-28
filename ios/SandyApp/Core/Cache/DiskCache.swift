import Foundation

/// كاش «بدون إنترنت»: Application Support/SandyCache/<userId>/<key>.json.
/// المستدعي بيمرّر `currentUserId` لحظة الحفظ (بعد الـawait) حتى جلب طاير وقت الخروج ما يكتب.
enum DiskCache {
    private static let queue = DispatchQueue(label: "sandy.diskcache", qos: .utility)

    private static var root: URL? {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first?
            .appendingPathComponent("SandyCache", isDirectory: true)
    }

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

    static func load<T: Decodable>(_ type: T.Type, key: String, userId: String?) -> T? {
        guard let url = fileURL(key: key, userId: userId),
              let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(T.self, from: data)
    }

    /// فشل الحفظ صامت — الكاش تحسين، مش مصدر حقيقة.
    static func save<T: Encodable>(_ value: T, key: String, userId: String?) {
        guard let url = fileURL(key: key, userId: userId),
              let data = try? JSONEncoder().encode(value) else { return }
        queue.async {
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                     withIntermediateDirectories: true)
            try? data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        }
    }

    /// على نفس الطابور التسلسلي، فأي حفظ سبقه بينكتب ثم بينمسح.
    static func clearAll() {
        guard let root else { return }
        queue.async { try? FileManager.default.removeItem(at: root) }
    }
}
