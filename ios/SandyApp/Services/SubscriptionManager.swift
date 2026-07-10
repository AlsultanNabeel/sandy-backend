import Foundation
#if canImport(RevenueCat)
import RevenueCat
#endif

/// مدير الاشتراك (المرحلة السابعة). RevenueCat مصدر الحقيقة للفوترة، والباك-إند
/// يعكس الحالة عبر الويبهوك؛ هون نربط الشراء بالتطبيق ونعرض حالة الباك-إند.
///
/// مبني حتى **يبني بدون حزمة RevenueCat**: كل نداءات RevenueCat محاطة بـ
/// `#if canImport(RevenueCat)`، فلو الحزمة مش مضافة الواجهة تشتغل وتعرض الحالة
/// من الباك-إند وتعطّل زر الشراء. أول ما تضيف الحزمة بإكس-كود يشتغل الشراء تلقائيًا
/// بدون أي تعديل كود — بس عبّي `revenueCatAPIKey` بمفتاح RevenueCat العام.
@MainActor
final class SubscriptionManager: ObservableObject {
    /// مفتاح RevenueCat العام (public SDK key) — يُشحن بالتطبيق (مش سرّي).
    /// عبّيه بعد إنشاء مشروع RevenueCat. فاضي = ما ننادي الإعداد.
    static let revenueCatAPIKey = ""

    @Published var status: SubscriptionStatus?
    @Published var busy = false
    @Published var priceText = ""       // من العرض الحالي (لو RevenueCat موجود)
    @Published var lastError: String?

    /// هل الشراء متاح فعليًا (الحزمة مركّبة + مفتاح موجود)؟ الواجهة تعطّل الزر لو لأ.
    var purchasesAvailable: Bool {
        #if canImport(RevenueCat)
        return !Self.revenueCatAPIKey.isEmpty
        #else
        return false
        #endif
    }

    var isSubscriber: Bool { status?.isSubscriber ?? false }

    /// إعداد RevenueCat مرّة بعد الدخول. نمرّر user_id حتى app_user_id يطابق حساب
    /// الباك-إند (الويبهوك يكتب على نفس الـid). idempotent — آمن للتكرار.
    func configure(userId: String?) {
        #if canImport(RevenueCat)
        guard !Self.revenueCatAPIKey.isEmpty else { return }
        Purchases.logLevel = .warn
        Purchases.configure(withAPIKey: Self.revenueCatAPIKey, appUserID: userId)
        Task { await loadOffering() }
        #endif
    }

    /// حالة الاشتراك من الباك-إند (تعمل دائمًا، بلا RevenueCat).
    func refresh(api: APIClient) async {
        status = try? await api.getSubscription()
    }

    /// شراء الاشتراك؛ عند النجاح نعكس حالة الباك-إند فورًا (الويبهوك يكتبها كمان).
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

    /// استرجاع مشتريات سابقة (لجهاز جديد / إعادة تثبيت).
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
