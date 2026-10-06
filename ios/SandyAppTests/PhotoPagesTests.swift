import XCTest
@testable import SandyApp

/// The album shows its first page and the next as the grid reaches the end; it used to stop
/// at the server's first 200 photos with no way past them.
@MainActor
final class PhotoPagesTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    private func page(_ range: Range<Int>, next: String?) -> Data {
        let items = range.map { #"{"id":"p\#($0)","name":"","caption":"","tags":[],"created_at":""}"# }
        let nextField = next.map { #","next":"\#($0)""# } ?? ""
        return Data(#"{"items":[\#(items.joined(separator: ","))]\#(nextField)}"#.utf8)
    }

    func testTheNextPageComesWhenAsked() async {
        StubNetwork.install { request in
            let url = request.url!.absoluteString
            if url.contains("/albums") { return (200, Data(#"{"items":[]}"#.utf8)) }
            if url.contains("before=") { return (200, self.page(200..<250, next: nil)) }
            return (200, self.page(0..<200, next: "2026-01-01T00:00:00+00:00|p199"))
        }
        let store = PhotosStore()
        let api = TestClient.make()
        await store.load(api: api)
        XCTAssertEqual(store.photos.count, 200)
        XCTAssertTrue(store.hasMore)
        await store.loadMore(api: api)
        XCTAssertEqual(store.photos.count, 250)
        XCTAssertFalse(store.hasMore)
        let asked = StubNetwork.requests.map { $0.url!.absoluteString }
        XCTAssertTrue(asked.contains { $0.contains("before=2026-01-01T00%3A00%3A00%2B00%3A00%7Cp199")
                                       || $0.contains("before=2026-01-01T00:00:00%2B00:00%7Cp199") },
                      asked.joined(separator: "\n"))
    }
}
