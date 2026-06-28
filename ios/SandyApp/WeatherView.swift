import SwiftUI

// ─────────────────────────────────────────────────────────────────────────
//  Weather — شاشة الطقس + بطاقة مصغّرة للشاشة الرئيسية.
//
//  المصدر: GET /api/weather?city=<اسم المدينة> — غلاف رفيع حول نفس مُحرّك
//  الطقس اللي تستعمله ساندي بالشات. الموقع = نص حر للمدينة يكتبه المستخدم،
//  بنحفظ آخر مدينة بالـ UserDefaults حتى ترجع نفسها كل مرة. الباك-إند يرجّع
//  لقطة اليوم فقط (الحالة الحالية + عظمى/صغرى اليوم + الغروب) — ما في توقّع
//  أيام، فما بنخترع شي مش موجود.
//
//  نمط الستور المعتمد (مرآة MemoryStore): الجلب بمهمة يملكها الستور.
// ─────────────────────────────────────────────────────────────────────────

// MARK: - النموذج

/// لقطة طقس — تطابق مفاتيح GET /api/weather. wttr.in يرجّع الأرقام كنصوص،
/// فنخزّنها نصوصًا ونعرضها كما هي (مع رمز الدرجة عند العرض).
struct WeatherSnapshot {
    let city: String
    let description: String
    let tempC: String
    let feelsLikeC: String
    let humidity: String
    let maxTempC: String
    let minTempC: String
    let sunset: String
}

extension WeatherSnapshot {
    /// أيقونة SF Symbol مناسبة حسب وصف الحالة (عربي/إنجليزي من wttr.in).
    var symbol: String {
        let d = description.lowercased()
        func has(_ words: [String]) -> Bool { words.contains { d.contains($0) } }
        if has(["thunder", "رعد", "عاصف"]) { return "cloud.bolt.rain.fill" }
        if has(["snow", "ثلج", "sleet"]) { return "cloud.snow.fill" }
        if has(["rain", "drizzle", "مطر", "shower"]) { return "cloud.rain.fill" }
        if has(["fog", "mist", "ضباب", "haze"]) { return "cloud.fog.fill" }
        if has(["overcast", "غائم كلي", "cloud", "غيوم", "غائم"]) { return "cloud.fill" }
        if has(["partly", "جزئي"]) { return "cloud.sun.fill" }
        if has(["clear", "sunny", "صافي", "مشمس", "شمس"]) { return "sun.max.fill" }
        return "cloud.sun.fill"
    }

    /// درجة الحرارة الحالية مع رمز الدرجة (مثلاً "24°").
    var tempDisplay: String { "\(tempC)°" }
}

// MARK: - APIClient (نداء الطقس)

extension APIClient {
    /// GET /api/weather?city= → لقطة طقس اليوم. مدينة فاضية = افتراضي الباك-إند.
    /// المفاتيح كلها نصوص (wttr.in يرجّع الأرقام نصوصًا).
    func weatherNow(city: String) async throws -> WeatherSnapshot {
        let trimmed = city.trimmingCharacters(in: .whitespacesAndNewlines)
        let q = trimmed.isEmpty
            ? ""
            : "?city=\(trimmed.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")"
        let r = try await request("/api/weather\(q)")
        return WeatherSnapshot(
            city: r["city"] as? String ?? trimmed,
            description: r["description"] as? String ?? "",
            tempC: r["temp_c"] as? String ?? "",
            feelsLikeC: r["feels_like_c"] as? String ?? "",
            humidity: r["humidity"] as? String ?? "",
            maxTempC: r["max_temp_c"] as? String ?? "",
            minTempC: r["min_temp_c"] as? String ?? "",
            sunset: r["sunset"] as? String ?? "")
    }
}

// MARK: - الستور

@MainActor
final class WeatherStore: ObservableObject {
    @Published var snapshot: WeatherSnapshot?
    @Published var city: String
    @Published var loading = false
    @Published var notice = ""

    /// مفتاح حفظ آخر مدينة — تُسترجع تلقائيًا عند الإقلاع.
    private static let cityKey = "sandy_weather_city"

    private var loadTask: Task<Void, Never>?

    init() {
        city = UserDefaults.standard.string(forKey: Self.cityKey) ?? ""
    }

    /// جلب الطقس للمدينة الحالية بمهمة يملكها الستور (تُلغى عند إعادة الطلب).
    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            do {
                snapshot = try await api.weatherNow(city: city)
                notice = ""
            } catch {
                if !error.isCancellation {
                    notice = LanguageManager.shared.s("weather.errorLoad")
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

// MARK: - الشاشة الكاملة

/// شاشة الطقس الكاملة — لقطة كبيرة + تفاصيل (شعور/رطوبة/عظمى/صغرى/غروب) +
/// حقل لتغيير المدينة (يُحفظ آخرها). الجلب عبر ستور يملكه العرض.
struct WeatherView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = WeatherStore()
    @State private var showCityEditor = false

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                content
            }
        }
        .navigationTitle(lang.s("weather.title"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                SandyButton(title: lang.s("weather.change"),
                            systemImage: "mappin.and.ellipse",
                            style: .secondary) {
                    store.notice = ""
                    showCityEditor = true
                }
            }
        }
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .animation(.spring(response: 0.45, dampingFraction: 0.85), value: store.snapshot?.city)
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .fullScreenCover(isPresented: $showCityEditor) {
            WeatherCityEditor(initial: store.city) { newCity in
                await store.setCity(newCity, api: state.api)
                return true
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if let snap = store.snapshot {
            ScrollView {
                VStack(spacing: Theme.Spacing.lg) {
                    Text(lang.s("weather.intro"))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .frame(maxWidth: .infinity, alignment: .leading)

                    heroCard(snap)
                    detailsGrid(snap)
                }
                .padding(Theme.Spacing.md)
            }
        } else if store.loading {
            ProgressView()
                .tint(Theme.Colors.accent)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            emptyView
        }
    }

    private func heroCard(_ snap: WeatherSnapshot) -> some View {
        SandyCard {
            VStack(spacing: Theme.Spacing.sm) {
                Image(systemName: snap.symbol)
                    .font(.system(size: 64))
                    .symbolRenderingMode(.multicolor)
                    .foregroundColor(Theme.Colors.accent)
                Text(snap.tempDisplay)
                    .font(.system(size: 56, weight: .bold, design: .rounded))
                    .foregroundColor(Theme.Colors.primaryText)
                Text(snap.description)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                    .multilineTextAlignment(.center)
                HStack(spacing: Theme.Spacing.xs) {
                    Image(systemName: "mappin.circle.fill")
                        .font(.caption)
                    Text(snap.city)
                        .font(Theme.Typography.callout)
                }
                .foregroundColor(Theme.Colors.secondaryText)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, Theme.Spacing.sm)
        }
    }

    private func detailsGrid(_ snap: WeatherSnapshot) -> some View {
        let cols = [GridItem(.flexible(), spacing: Theme.Spacing.md),
                    GridItem(.flexible(), spacing: Theme.Spacing.md)]
        return LazyVGrid(columns: cols, spacing: Theme.Spacing.md) {
            detailCell(icon: "thermometer.medium", title: lang.s("weather.feelsLike"),
                       value: "\(snap.feelsLikeC)°")
            detailCell(icon: "humidity.fill", title: lang.s("weather.humidity"),
                       value: "\(snap.humidity)%")
            detailCell(icon: "arrow.up", title: lang.s("weather.high"),
                       value: "\(snap.maxTempC)°")
            detailCell(icon: "arrow.down", title: lang.s("weather.low"),
                       value: "\(snap.minTempC)°")
            if !snap.sunset.isEmpty {
                detailCell(icon: "sunset.fill", title: lang.s("weather.sunset"),
                           value: snap.sunset)
            }
        }
    }

    private func detailCell(icon: String, title: String, value: String) -> some View {
        SandyCard {
            HStack(spacing: Theme.Spacing.md) {
                Image(systemName: icon)
                    .font(.title3)
                    .foregroundColor(Theme.Colors.accent)
                    .frame(width: 28)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                    Text(value)
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                }
                Spacer(minLength: 0)
            }
        }
    }

    private var emptyView: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "cloud.sun.fill")
                .font(.system(size: 44))
                .foregroundColor(Theme.Colors.accent.opacity(0.5))
            Text(lang.s("weather.empty"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
            SandyButton(title: lang.s("weather.change"),
                        systemImage: "mappin.and.ellipse") {
                store.notice = ""
                showCityEditor = true
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Theme.Spacing.lg)
    }
}

// MARK: - محرّر المدينة

/// نافذة منبثقة بسيطة لتغيير مدينة الطقس. تُرسل عبر closure غير متزامن يرجّع
/// نجاح/فشل لتقرّر النافذة تتقفل (مرآة MemorySheet).
private struct WeatherCityEditor: View {
    let initial: String
    let onSubmit: (_ city: String) async -> Bool

    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    @State private var city: String
    @State private var submitting = false

    init(initial: String, onSubmit: @escaping (_ city: String) async -> Bool) {
        self.initial = initial
        self.onSubmit = onSubmit
        _city = State(initialValue: initial)
    }

    private var trimmed: String { city.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        SandyPopup(title: lang.s("weather.change")) {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                SectionHeader(title: lang.s("weather.cityField"))
                SandyCard {
                    TextField(lang.s("weather.cityPlaceholder"), text: $city)
                        .font(Theme.Typography.body)
                        .submitLabel(.done)
                        .onSubmit(save)
                }
                SandyButton(title: lang.s("weather.save"),
                            systemImage: "checkmark.circle.fill",
                            isLoading: submitting,
                            fillWidth: true) {
                    save()
                }
                .disabled(trimmed.isEmpty)
                .opacity(trimmed.isEmpty ? 0.5 : 1)
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func save() {
        guard !trimmed.isEmpty, !submitting else { return }
        submitting = true
        Task {
            let ok = await onSubmit(trimmed)
            submitting = false
            if ok { dismiss() }
        }
    }
}

// MARK: - بطاقة مصغّرة للشاشة الرئيسية

/// بطاقة طقس مختصرة وقائمة بذاتها (بلا معطيات) — تملك ستورها الخاص وتجلب عند
/// الظهور. تعرض الأيقونة + الحرارة + الحالة + المدينة. مخصّصة للتركيب على الشاشة
/// الرئيسية. تستعمل APIClient من البيئة (AppState).
struct WeatherCard: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = WeatherStore()

    var body: some View {
        SandyCard {
            Group {
                if let snap = store.snapshot {
                    loaded(snap)
                } else if store.loading {
                    ProgressView()
                        .tint(Theme.Colors.accent)
                        .frame(maxWidth: .infinity, minHeight: 56)
                } else {
                    HStack(spacing: Theme.Spacing.md) {
                        Image(systemName: "cloud.sun.fill")
                            .font(.title2)
                            .foregroundColor(Theme.Colors.accent.opacity(0.6))
                        Text(lang.s("weather.empty"))
                            .font(Theme.Typography.subheadline)
                            .foregroundColor(Theme.Colors.secondaryText)
                        Spacer(minLength: 0)
                    }
                }
            }
        }
        .task { await store.load(api: state.api) }
    }

    private func loaded(_ snap: WeatherSnapshot) -> some View {
        HStack(spacing: Theme.Spacing.md) {
            Image(systemName: snap.symbol)
                .font(.system(size: 36))
                .symbolRenderingMode(.multicolor)
                .foregroundColor(Theme.Colors.accent)
            VStack(alignment: .leading, spacing: 2) {
                Text(snap.tempDisplay)
                    .font(Theme.Typography.title)
                    .foregroundColor(Theme.Colors.primaryText)
                Text(snap.description)
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            HStack(spacing: Theme.Spacing.xs) {
                Image(systemName: "mappin.circle.fill")
                    .font(.caption)
                Text(snap.city)
                    .font(Theme.Typography.caption)
                    .lineLimit(1)
            }
            .foregroundColor(Theme.Colors.secondaryText)
        }
    }
}
