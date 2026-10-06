import SwiftUI

extension APIClient {
    /// كل المفاتيح نصوص اختيارية (wttr.in بيرجّع الأرقام نصوصًا).
    private struct WeatherResponse: Decodable {
        let city: String?
        let description: String?
        let temp_c: String?
        let feels_like_c: String?
        let humidity: String?
        let max_temp_c: String?
        let min_temp_c: String?
        let sunset: String?
    }

    /// مدينة فاضية = افتراضي الباك-إند.
    func weatherNow(city: String) async throws -> WeatherSnapshot {
        let trimmed = city.trimmingCharacters(in: .whitespacesAndNewlines)
        let q = trimmed.isEmpty
            ? ""
            : "?city=\(URLEscape.query(trimmed))"
        let r: WeatherResponse = try await fetch("/api/weather\(q)")
        return WeatherSnapshot(
            city: r.city ?? trimmed,
            description: r.description ?? "",
            tempC: r.temp_c ?? "",
            feelsLikeC: r.feels_like_c ?? "",
            humidity: r.humidity ?? "",
            maxTempC: r.max_temp_c ?? "",
            minTempC: r.min_temp_c ?? "",
            sunset: r.sunset ?? "")
    }
}
