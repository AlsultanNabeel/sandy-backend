import Foundation

/// Text with its links tappable: web addresses, and the app's own `sandy://` links Sandy hands
/// out in a reply (sign in to a site, watch «Sandy's browser»), which the app opens itself.
enum Linked {
    private static let own = try? NSRegularExpression(pattern: #"sandy://[^\s«»"]+"#)

    static func text(_ plain: String) -> AttributedString {
        var shown = AttributedString(plain)
        let whole = NSRange(plain.startIndex..., in: plain)
        let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
        var found: [(NSRange, URL)] = (detector?.matches(in: plain, range: whole) ?? [])
            .compactMap { m in m.url.map { (m.range, $0) } }
        for m in own?.matches(in: plain, range: whole) ?? [] {
            guard let range = Range(m.range, in: plain), let url = URL(string: String(plain[range])) else { continue }
            found.removeAll { NSIntersectionRange($0.0, m.range).length > 0 }
            found.append((m.range, url))
        }
        for (nsRange, url) in found {
            guard let range = Range(nsRange, in: plain),
                  let lower = AttributedString.Index(range.lowerBound, within: shown),
                  let upper = AttributedString.Index(range.upperBound, within: shown) else { continue }
            shown[lower..<upper].link = url
        }
        return shown
    }
}
