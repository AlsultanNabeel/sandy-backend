import Foundation

/// The one way a value goes into a URL. `.urlQueryAllowed` alone lets `&`, `+` and `=`
/// through, so «Tom & Jerry» became two parameters and «C++» arrived with spaces; and a
/// path built with it let a `/` in a device name split the path.
enum URLEscape {
    private static let queryValue: CharacterSet = {
        var set = CharacterSet.urlQueryAllowed
        set.remove(charactersIn: "&+=?#/")
        return set
    }()

    private static let pathSegment: CharacterSet = {
        var set = CharacterSet.urlPathAllowed
        set.remove(charactersIn: "/?#;")
        return set
    }()

    /// A value after `name=` in a query.
    static func query(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: queryValue) ?? ""
    }

    /// One segment of a path (an id or a name between two slashes).
    static func segment(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: pathSegment) ?? ""
    }
}
