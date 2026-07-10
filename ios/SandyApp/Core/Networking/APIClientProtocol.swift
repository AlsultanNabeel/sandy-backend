import Foundation

/// The transport seam every backend call routes through.
///
/// The concrete `APIClient` owns the URL session, the Keychain-backed token, and
/// the one `request(_:)` primitive; each feature's endpoints live in an
/// `APIClient+<Feature>` extension that builds on that primitive. Declaring the
/// core surface here lets call sites — and, once an iOS test target exists, a
/// mock — depend on an interface instead of the concrete singleton. The
/// per-domain surface can be grown onto this protocol incrementally without
/// touching call sites, since `APIClient` already satisfies it.
protocol APIClientProtocol: AnyObject {
    var baseURL: String { get set }
    var token: String? { get set }
    var onUnauthorized: (() -> Void)? { get set }
    var currentUserId: String? { get }

    func request(
        _ path: String,
        method: String,
        body: [String: Any]?,
        auth: Bool
    ) async throws -> [String: Any]
}
