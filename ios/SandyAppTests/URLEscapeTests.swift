import XCTest
@testable import SandyApp

/// A search for «Tom & Jerry» sent `q=Tom` and a stray `Jerry` parameter; «C++» arrived as
/// «C  » (a `+` is a space in a query); a device named «ضو/صالون» split the path in two.
final class URLEscapeTests: XCTestCase {
    func testAQueryValueKeepsItsAmpersandPlusAndEquals() {
        XCTAssertEqual(URLEscape.query("Tom & Jerry"), "Tom%20%26%20Jerry")
        XCTAssertEqual(URLEscape.query("C++"), "C%2B%2B")
        XCTAssertEqual(URLEscape.query("a=b?#/"), "a%3Db%3F%23%2F")
        XCTAssertEqual(URLEscape.query("البحر"), "البحر".addingPercentEncoding(withAllowedCharacters: .alphanumerics))
    }

    func testAPathSegmentStaysOneSegment() throws {
        let light = try XCTUnwrap("ضو".addingPercentEncoding(withAllowedCharacters: .alphanumerics))
        let salon = try XCTUnwrap("صالون".addingPercentEncoding(withAllowedCharacters: .alphanumerics))
        XCTAssertEqual(URLEscape.segment("ضو/صالون?x#y"), light + "%2F" + salon + "%3Fx%23y")
    }

    override func tearDown() { StubNetwork.uninstall() }

    func testTheClientSendsThemEscaped() async throws {
        StubNetwork.install(json: #"{"items": []}"#)
        _ = try await TestClient.make().searchConversations(q: "Tom & Jerry")
        let search = try XCTUnwrap(StubNetwork.requests.first?.url?.absoluteString)
        StubNetwork.install(json: #"{"ok": true}"#)
        try await TestClient.make().deleteDevice(name: "ضو/صالون")
        let device = try XCTUnwrap(StubNetwork.requests.first?.url?.absoluteString)
        XCTAssertTrue(search.hasSuffix("q=Tom%20%26%20Jerry"), search)
        XCTAssertTrue(device.contains("/api/devices/%D8%B6%D9%88%2F"), device)
    }
}
