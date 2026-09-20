import SwiftUI

@MainActor
final class WeatherStore: LoadableStore {
    @Published var snapshot: WeatherSnapshot?
    @Published var city: String

    /// مفتاح حفظ آخر مدينة — تُسترجع تلقائيًا عند الإقلاع.
    private static let cityKey = "sandy_weather_city"

    private var loadTask: Task<Void, Never>?

    override init() {
        city = UserDefaults.standard.string(forKey: Self.cityKey) ?? ""
    }

    /// جلب الطقس للمدينة الحالية بمهمة يملكها الستور (تُلغى عند إعادة الطلب).
    func load(api: APIClient) async {
        loadTask?.cancel()
        let gen = beginLoad()
        let task = Task { @MainActor in
            defer { endLoad(gen) }
            do {
                let r = try await api.weatherNow(city: city)
                guard isCurrentLoad(gen) else { return }
                snapshot = r
                clearNotice()
            } catch {
                if !error.isCancellation, isCurrentLoad(gen) {
                    notify("weather.errorLoad")
                }
            }
        }
        loadTask = task
        await task.value
    }

    /// غيّر المدينة، احفظها، وأعد الجلب.
    func setCity(_ newCity: String, api: APIClient) async {
        let trimmed = newCity.trimmingCharacters(in: .whitespacesAndNewlines)
        city = trimmed
        UserDefaults.standard.set(trimmed, forKey: Self.cityKey)
        await load(api: api)
    }
}
