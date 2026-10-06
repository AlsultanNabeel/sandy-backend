import Foundation
@testable import SandyApp

/// Answers the app's requests in tests: no server, nothing leaves the machine.
/// `install` swaps `APIClient.session` for one that routes through `StubURLProtocol`;
/// `uninstall` (in tearDown) puts the real one back.
enum StubNetwork {
    private static var original: URLSession?

    static func install(_ handler: @escaping (URLRequest) -> (status: Int, body: Data)) {
        StubURLProtocol.handler = handler
        StubURLProtocol.requests = []
        if original == nil { original = APIClient.session }
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubURLProtocol.self]
        APIClient.session = URLSession(configuration: config)
    }

    /// One JSON body for every request.
    static func install(status: Int = 200, json: String) {
        install { _ in (status, Data(json.utf8)) }
    }

    static func uninstall() {
        if let original { APIClient.session = original }
        original = nil
        StubURLProtocol.handler = nil
        StubURLProtocol.delays = [:]
    }

    /// Answer requests of this method only after `seconds`, without holding up the others
    /// (a command still on its way while a refresh comes back).
    static func delay(_ method: String, by seconds: TimeInterval) {
        StubURLProtocol.delays[method] = seconds
    }

    /// What the app sent, in order (the body read whole, also for uploads).
    static var requests: [URLRequest] { StubURLProtocol.requests }

    static func body(of request: URLRequest) -> Data {
        if let data = request.httpBody { return data }
        guard let stream = request.httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let n = stream.read(&buffer, maxLength: buffer.count)
            if n <= 0 { break }
            data.append(buffer, count: n)
        }
        return data
    }
}

final class StubURLProtocol: URLProtocol {
    static var handler: ((URLRequest) -> (status: Int, body: Data))?
    static var requests: [URLRequest] = []
    static var delays: [String: TimeInterval] = [:]

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        var seen = request
        seen.httpBody = StubNetwork.body(of: request)
        Self.requests.append(seen)
        let (status, body) = Self.handler?(seen) ?? (500, Data())
        let response = HTTPURLResponse(url: request.url!, statusCode: status,
                                       httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Type": "application/json"])!
        let deliver = { [weak self] in
            guard let self else { return }
            self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            self.client?.urlProtocol(self, didLoad: body)
            self.client?.urlProtocolDidFinishLoading(self)
        }
        if let wait = Self.delays[request.httpMethod ?? "GET"], wait > 0 {
            DispatchQueue.global().asyncAfter(deadline: .now() + wait, execute: deliver)
        } else {
            deliver()
        }
    }

    override func stopLoading() {}
}
