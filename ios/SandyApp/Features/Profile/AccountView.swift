import SwiftUI

/// حسابك وروبوتك — وكيف تتخلّى عن الاتنين.
///
/// **الشاشة كلها مبنية حوالين لحظتين ما حدا بيفكّر فيهن وهو بيبني:** لمّا تبيع
/// الروبوت، ولمّا تقرّر تمشي.
///
/// البيع بده إشيين مش واحد. فكّ الملكية ع الخادم بيخلّي المشتري يقدر يربط. بس
/// اللوح نفسه بيضلّ حافظ **اسم شبكتك وكلمة سرّها** بذاكرته — فالمشتري بيشغّله
/// وهو بيحاول يدخل ع شبكة ببيتك. عشان هيك الزرّ بيمسح اللوح كمان، وبيقولك إذا
/// وصلته الرسالة: لوح مطفي وقتها بينباع وجوّاه بياناتك.
///
/// والحذف حذف. الحساب فيه بصمة صوتك ويومياتك وصورك ومصاريفك وكل جملة حكيتها
/// لساندي — «تعطيل» مش جواب أمين لحدا طالب إنّ هاد يروح. وأبل بترفض التطبيق
/// أصلًا بدون هالزرّ.
struct AccountView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @State private var code = ""
    @State private var nodes: [NodeItem] = []
    @State private var notice = ""
    @State private var busy = false
    @State private var confirmingDelete = false
    @State private var confirmingReset = false
    @State private var sellNode: NodeItem?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.section) {
                pairSection
                if !nodes.isEmpty { robotsSection }
                dangerSection
                if !notice.isEmpty { SandyNotice(notice, kind: .gentleWarning) }
            }
            .padding(Theme.Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .navigationTitle(lang.s("account.title"))
        .task { await reload() }
    }

    // ── ربط روبوت ────────────────────────────────────────────────────────────

    private var pairSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            SectionHeader(title: lang.s("account.pair"))
            Text(lang.s("account.pair.hint"))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)

            TextField(lang.s("account.pair.code"), text: $code)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()

            SandyButton(title: lang.s("account.pair.button"),
                        systemImage: "link", isLoading: busy, fillWidth: true) {
                Task { await pair() }
            }
            .disabled(code.trimmingCharacters(in: .whitespaces).isEmpty || busy)
        }
    }

    // ── روبوتاتك ─────────────────────────────────────────────────────────────

    private var robotsSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            SectionHeader(title: lang.s("account.robots"))
            ForEach(nodes, id: \.nodeId) { n in
                HStack(spacing: Theme.Spacing.md) {
                    Image(systemName: n.online ? "wifi" : "wifi.slash")
                        .foregroundColor(n.online ? Theme.Colors.success
                                                  : Theme.Colors.tertiaryText)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(n.label.isEmpty ? n.nodeId : n.label)
                            .font(Theme.Typography.headline)
                        Text(n.nodeId)
                            .font(Theme.Typography.caption.monospacedDigit())
                            .foregroundColor(Theme.Colors.tertiaryText)
                    }
                    Spacer(minLength: 0)
                    Button(lang.s("account.sell")) { sellNode = n }
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.warn)
                }
                .sandyCard()
            }
        }
        // تأكيد لأنّ الفعل ما إله رجعة من التطبيق: بعده بدك تكون ماسك اللوح.
        .alert(lang.s("account.sell.confirm"), isPresented: .constant(sellNode != nil)) {
            Button(lang.s("common.cancel"), role: .cancel) { sellNode = nil }
            Button(lang.s("account.sell"), role: .destructive) {
                if let n = sellNode { Task { await unpair(n) } }
            }
        } message: {
            Text(lang.s("account.sell.warn"))
        }
    }

    // ── حذف الحساب ───────────────────────────────────────────────────────────

    private var dangerSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            SectionHeader(title: lang.s("account.danger"))

            // «صفّر» قبل «احذف»، وهاد ترتيب مقصود.
            //
            // أغلب اللي بيوصل لهون بدّه يفضّي مش يمشي. لو الحذف كان الخيار
            // الوحيد، رح يحذف حسابه عشان يمسح محادثة — ويخسر روبوته معها.
            Text(lang.s("account.reset.warn"))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
            SandyButton(title: lang.s("account.reset"),
                        systemImage: "arrow.counterclockwise",
                        style: .secondary, fillWidth: true) {
                confirmingReset = true
            }

            Divider().overlay(Theme.Colors.border)

            Text(lang.s("account.delete.warn"))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
            SandyButton(title: lang.s("account.delete"),
                        systemImage: "trash", style: .secondary, fillWidth: true) {
                confirmingDelete = true
            }
        }
        .alert(lang.s("account.delete.confirm"), isPresented: $confirmingDelete) {
            Button(lang.s("common.cancel"), role: .cancel) {}
            Button(lang.s("account.delete"), role: .destructive) {
                Task { await deleteAccount() }
            }
        } message: {
            Text(lang.s("account.delete.warn"))
        }
        .alert(lang.s("account.reset.confirm"), isPresented: $confirmingReset) {
            Button(lang.s("common.cancel"), role: .cancel) {}
            Button(lang.s("account.reset"), role: .destructive) {
                Task { await resetData() }
            }
        } message: {
            Text(lang.s("account.reset.warn"))
        }
    }

    // ── الأفعال ──────────────────────────────────────────────────────────────

    private func reload() async {
        nodes = (try? await state.api.getNodes())?.items ?? []
    }

    private func pair() async {
        busy = true; notice = ""
        defer { busy = false }
        do {
            _ = try await state.api.pairNode(
                code: code.trimmingCharacters(in: .whitespaces), label: nil)
            code = ""
            await reload()
        } catch {
            // `already_claimed` بيستاهل جملته الخاصة: «هاد الروبوت مربوط بحساب
            // تاني» شغلة بتقدر تعملها (ارجع لصاحبه يفكّه)، و«فشل الربط» لأ.
            //
            // المطابقة على `code` — الرمز الآلي — مش على `message`. كانت على
            // النص، فأول ما يبعت الخادم جملة عربية جنب الرمز بتفشل بصمت
            // وبتنزل ع «فشل الربط» العامة.
            let m = (error as? APIError)?.code ?? ""
            notice = m == "already_claimed" ? lang.s("account.pair.taken")
                   : m == "too_many_attempts" ? lang.s("account.pair.tooMany")
                   : lang.s("account.pair.failed")
        }
    }

    private func unpair(_ n: NodeItem) async {
        sellNode = nil
        do {
            let wiped = try await state.api.unpairNode(nodeId: n.nodeId)
            notice = wiped ? lang.s("account.sell.done") : lang.s("account.sell.offline")
            await reload()
        } catch {
            notice = lang.s("account.sell.failed")
        }
    }

    private func resetData() async {
        do {
            try await state.api.resetAccountData()
            notice = lang.s("account.reset.done")
            await reload()
        } catch {
            notice = lang.s("account.reset.failed")
        }
    }

    private func deleteAccount() async {
        do {
            try await state.api.deleteAccount()
            state.signOut()
        } catch {
            notice = lang.s("account.delete.failed")
        }
    }
}
