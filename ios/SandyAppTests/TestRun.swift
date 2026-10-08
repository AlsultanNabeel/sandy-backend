import XCTest
@testable import SandyApp

/// The test bundle's principal class (`INFOPLIST_KEY_NSPrincipalClass`). The tests invent an
/// account per test (a new id each run) and the stores keep a cache folder for each, in the
/// host app's container. Every folder made during the run is removed when it ends: they used
/// to pile up (over a thousand), and the one test that wipes the whole cache walked them all.
@objc(SandyTestRun)
final class TestRun: NSObject, XCTestObservation {
    private var before: Set<String> = []

    override init() {
        super.init()
        XCTestObservationCenter.shared.addTestObserver(self)
    }

    func testBundleWillStart(_ testBundle: Bundle) {
        before = Self.folders()
    }

    func testBundleDidFinish(_ testBundle: Bundle) {
        // What the last tests queued is written first, so nothing lands after the removal.
        let written = DispatchSemaphore(value: 0)
        Task.detached {
            await DiskCache.written()
            written.signal()
        }
        _ = written.wait(timeout: .now() + 10)
        guard let root = DiskCache.root else { return }
        for name in Self.folders().subtracting(before) {
            try? FileManager.default.removeItem(at: root.appendingPathComponent(name))
        }
    }

    private static func folders() -> Set<String> {
        guard let root = DiskCache.root else { return [] }
        return Set((try? FileManager.default.contentsOfDirectory(atPath: root.path)) ?? [])
    }
}
