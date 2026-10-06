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

    #if canImport(RevenueCat)
    /// `Purchases.configure` runs once per launch; later sign-ins switch the user with `logIn`.
    private var configured = false
    #endif

    /// نمرّر user_id حتى app_user_id يطابق حساب الباك-إند (الويبهوك بيكتب عليه). آمن للتكرار.
    func configure(userId: String?) {
        #if canImport(RevenueCat)
        guard !Self.revenueCatAPIKey.isEmpty else { return }
        if configured {
            Task { await signIn(userId) }
            return
        }
        configured = true
        Purchases.logLevel = .warn
        Purchases.configure(withAPIKey: Self.revenueCatAPIKey, appUserID: userId)
        Task { await loadOffering() }
        #endif
    }

    /// Sign-out: the store's purchases must not follow the next account on this phone.
    func signOut() {
        status = nil
        #if canImport(RevenueCat)
        guard configured, !Purchases.shared.isAnonymous else { return }
        Task { _ = try? await Purchases.shared.logOut() }
        #endif
    }

    /// A failed refresh keeps what was known: one dropped request must not lock a subscriber out.
    func refresh(api: APIClient) async {
        if let fresh = try? await api.getSubscription() { status = fresh }
    }

    /// The features open once the server has the purchase (from the store's webhook), not on
    /// the store's word alone: asked a few times while the webhook lands.
    private func refreshUntilConfirmed(api: APIClient) async {
        for attempt in 0..<6 {
            await refresh(api: api)
            if isSubscriber { return }
            try? await Task.sleep(nanoseconds: UInt64(1 + attempt) * 1_000_000_000)
        }
    }

    func purchase(api: APIClient) async {
        #if canImport(RevenueCat)
        busy = true
        defer { busy = false }
        lastError = nil
        do {
            // The purchase must land on this account (the webhook writes to its id).
            await signIn(api.currentUserId)
            if cachedPackage == nil { await loadOffering() }
            guard let pkg = cachedPackage else { return }
            _ = try await Purchases.shared.purchase(package: pkg)
            await refreshUntilConfirmed(api: api)
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
        lastError = nil
        do {
            await signIn(api.currentUserId)
            _ = try await Purchases.shared.restorePurchases()
            await refreshUntilConfirmed(api: api)
        } catch {
            lastError = error.localizedDescription
        }
        #endif
    }

    #if canImport(RevenueCat)
    private var cachedPackage: Package?

    private func signIn(_ userId: String?) async {
        guard configured, let userId, !userId.isEmpty, Purchases.shared.appUserID != userId else { return }
        do {
            _ = try await Purchases.shared.logIn(userId)
        } catch {
            lastError = error.localizedDescription
        }
    }

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
