import XCTest
@testable import SandyApp

/// Arabic and English are equal: the app starts in the phone's language, tells the server
/// its language on every call, and says its own errors in it.
@MainActor
final class LanguageTests: XCTestCase {
    private var saved: String?

    override func setUp() {
        super.setUp()
        saved = UserDefaults.standard.string(forKey: "sandy_lang")
    }

    override func tearDown() {
        StubNetwork.uninstall()
        if let saved { UserDefaults.standard.set(saved, forKey: "sandy_lang") }
        else { UserDefaults.standard.removeObject(forKey: "sandy_lang") }
        super.tearDown()
    }

    func testTheFirstLanguageIsThePhones() {
        XCTAssertEqual(AppLang.initial(preferred: ["ar-JO", "en-US"]), .ar)
        XCTAssertEqual(AppLang.initial(preferred: ["en-GB"]), .en)
        XCTAssertEqual(AppLang.initial(preferred: ["fr-FR", "ar"]), .ar,
                       "the first language on the phone that the app speaks")
        XCTAssertEqual(AppLang.initial(preferred: ["fr-FR"]), .en,
                       "none the app speaks: English")
        XCTAssertEqual(AppLang.initial(preferred: []), .en)
    }

    func testEveryCallTellsTheServerTheAppsLanguage() async throws {
        UserDefaults.standard.set("en", forKey: "sandy_lang")
        let api = TestClient.make()
        StubNetwork.install(json: #"{"hidden": []}"#)
        _ = try await api.getFeatures()
        XCTAssertEqual(StubNetwork.requests.last?.value(forHTTPHeaderField: "X-Lang"), "en")
        UserDefaults.standard.set("ar", forKey: "sandy_lang")
        _ = try await api.getFeatures()
        XCTAssertEqual(StubNetwork.requests.last?.value(forHTTPHeaderField: "X-Lang"), "ar")
    }

    func testAConnectionErrorIsSaidInTheAppsLanguage() async {
        let api = TestClient.make()
        StubNetwork.install { _ in (StubNetwork.offline, Data()) }
        UserDefaults.standard.set("en", forKey: "sandy_lang")
        do { _ = try await api.getFeatures(); XCTFail("no error") }
        catch { XCTAssertEqual((error as? APIError)?.message, translate(.en, "errors.connection")) }
        UserDefaults.standard.set("ar", forKey: "sandy_lang")
        do { _ = try await api.getFeatures(); XCTFail("no error") }
        catch { XCTAssertEqual((error as? APIError)?.message, translate(.ar, "errors.connection")) }
        XCTAssertNotEqual(translate(.en, "errors.connection"), translate(.ar, "errors.connection"))
    }

    func testEveryErrorHasBothLanguages() {
        XCTAssertEqual(Set(L10nErrors.table.ar.keys), Set(L10nErrors.table.en.keys))
    }
}
