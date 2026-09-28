import Foundation
#if canImport(RevenueCat)
import RevenueCat
#endif

/// RevenueCat مصدر الحقيقة للفوترة، والباك-إند بيعكس الحالة عبر الويبهوك.
/// `#if canImport(RevenueCat)`: بلا الحزمة الواجهة بتعرض حالة الباك-إند والشراء معطّل.
@MainActor
final class SubscriptionManager: ObservableObject {
    /// مفتاح RevenueCat العام (مش سرّي). فاضي = ما ننادي الإعداد.
    static let revenueCatAPIKey = ""

    @Published var status: SubscriptionStatus?
    @Published var busy = false
    @Published var priceText = ""
    @Published var lastError: String?

    /// الحزمة مركّبة + مفتاح موجود؟ الواجهة تعطّل الزر لو لأ.
    var purchasesAvailable: Bool {
        #if canImport(RevenueCat)
        return !Self.revenueCatAPIKey.isEmpty
        #else
        return false
        #endif
    }

    var isSubscriber: Bool { status?.isSubscriber ?? false }

    /// نمرّر user_id حتى app_user_id يطابق حساب الباك-إند (الويبهوك بيكتب عليه). آمن للتكرار.
    func configure(userId: String?) {
        #if canImport(RevenueCat)
        guard !Self.revenueCatAPIKey.isEmpty else { return }
        Purchases.logLevel = .warn
        Purchases.configure(withAPIKey: Self.revenueCatAPIKey, appUserID: userId)
        Task { await loadOffering() }
        #endif
    }

    func refresh(api: APIClient) async {
        status = try? await api.getSubscription()
    }

    /// عند النجاح نعكس حالة الباك-إند فورًا.
    func purchase(api: APIClient) async {
        #if canImport(RevenueCat)
        busy = true
        defer { busy = false }
        do {
            if cachedPackage == nil { await loadOffering() }
            guard let pkg = cachedPackage else { return }
            _ = try await Purchases.shared.purchase(package: pkg)
            await refresh(api: api)
        } catch {
            lastError = error.localizedDescription
        }
        #endif
    }

    /// لجهاز جديد / إعادة تثبيت.
    func restore(api: APIClient) async {
        #if canImport(RevenueCat)
        busy = true
        defer { busy = false }
        do {
            _ = try await Purchases.shared.restorePurchases()
            await refresh(api: api)
        } catch {
            lastError = error.localizedDescription
        }
        #endif
    }

    #if canImport(RevenueCat)
    private var cachedPackage: Package?

    private func loadOffering() async {
        do {
            let offerings = try await Purchases.shared.offerings()
            if let pkg = offerings.current?.availablePackages.first {
                cachedPackage = pkg
                priceText = pkg.storeProduct.localizedPriceString
            }
        } catch {
            lastError = error.localizedDescription
        }
    }
    #endif
}
