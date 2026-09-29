import Foundation

/// Core transport surface of `APIClient`, so call sites and mocks can depend on an interface.
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
