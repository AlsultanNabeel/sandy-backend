import XCTest
@testable import SandyApp

/// M11: after the persona failed to load, «save» was open and wrote the default dialect and
/// empty instructions over the user's own.
@MainActor
final class PersonaFormTests: XCTestCase {
    override func tearDown() { StubNetwork.uninstall() }

    func testNothingIsSavedUntilThePersonaWasRead() async {
        StubNetwork.install(status: 500, json: #"{"error":"internal_error"}"#)
        let api = TestClient.make()
        let form = PersonaForm()
        await form.load(api: api)
        XCTAssertTrue(form.loadFailed)
        XCTAssertFalse(form.canSave)
        form.save(api: api)
        form.reset(api: api)
        try? await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertFalse(StubNetwork.requests.contains { $0.httpMethod == "POST" },
                       "the defaults were written over the saved persona")

        StubNetwork.install(json: #"{"dialect":"egyptian","custom_instructions":"اختصري","dialects":[]}"#)
        await form.load(api: api)
        XCTAssertTrue(form.canSave)
        XCTAssertFalse(form.loadFailed)
        XCTAssertEqual(form.dialect, "egyptian")
    }
}
