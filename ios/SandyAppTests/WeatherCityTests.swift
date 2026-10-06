import XCTest
@testable import SandyApp

/// Today and Profile › Weather each hold a weather store. A city picked in Profile used to
/// stay unseen by Today, which then saved its old city's weather over the new one.
@MainActor
final class WeatherCityTests: XCTestCase {
    private let key = "sandy_weather_city"
    private var saved: String?

    override func setUp() { saved = UserDefaults.standard.string(forKey: key) }

    override func tearDown() {
        UserDefaults.standard.set(saved, forKey: key)
        StubNetwork.uninstall()
    }

    func testACityPickedElsewhereIsTheOneLoaded() async throws {
        UserDefaults.standard.set("Cairo", forKey: key)
        let today = WeatherStore()
        StubNetwork.install(json: #"{"city":"Amman","description":"صافي","temp_c":"20"}"#)
        let api = TestClient.make()
        await WeatherStore().setCity("Amman", api: api)      // Profile › Weather
        await today.load(api: api)
        let last = try XCTUnwrap(StubNetwork.requests.last?.url?.absoluteString)
        XCTAssertTrue(last.hasSuffix("city=Amman"), last)
        XCTAssertEqual(today.city, "Amman")
    }
}
