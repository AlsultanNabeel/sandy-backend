import SwiftUI

/// نقل لوح لشبكة تانية — بلا كبل وبلا حرق.
///
/// **الشاشة كلها مبنية حوالين خطر واحد:** الطريقة الوحيدة اللي بنوصل فيها للوح
/// هي الشبكة اللي هو عليها. كلمة سر غلط بتقطعه، وبتقطع معها القناة اللي كنّا رح
/// نقوله فيها «ارجع». وساعتها ما إله حل غير كبل وحرق — بسبب حرف.
///
/// فاللوح بيجرّب الشبكة الجديدة، وإذا ما طلع عليها خلال خمسة وعشرين ثانية،
/// **بيرجع للقديمة لحاله**. الشاشة بتقول هاد قبل ما تدوس، مش بعدين: اللي بيعرف
/// إنه في رجوع تلقائي بيجرّب مطمّن، واللي ما بيعرف بيخاف من زرّ آمن.
///
/// وما في رسالة «نجح» من اللوح. النتيجة بتوصل بنبضته: اللي انتقل بيقول الاسم
/// الجديد، واللي رجع بيقول القديم. فالشاشة بتستنى النبضة وبتقرا منها — مصدر
/// واحد للحقيقة بدل رسالة تانية بتفترق عنه يوم ما.
struct NodeWiFiView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    let node: NodeItem
    /// بيتنده لما نبغى نعيد قراءة الوحدات بعد المحاولة.
    var onFinished: () async -> Void = {}

    @State private var ssid = ""
    @State private var password = ""
    @State private var phase: Phase = .idle
    @State private var notice = ""

    private enum Phase: Equatable {
        case idle
        case trying(secondsLeft: Int)
        case done(success: Bool)
    }

    private var currentSSID: String { node.telemetry?.ssid ?? "" }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.section) {
                currentCard
                form
                safetyNote
                if !notice.isEmpty { SandyNotice(notice, kind: .gentleWarning) }
            }
            .padding(Theme.Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .navigationTitle(lang.s("wifi.title"))
        .navigationBarTitleDisplayMode(.inline)
    }

    // ── الوضع الحالي ─────────────────────────────────────────────────────────

    private var currentCard: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            SectionHeader(title: lang.s("wifi.current"))
            HStack(spacing: Theme.Spacing.md) {
                Image(systemName: node.online ? "wifi" : "wifi.slash")
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(node.online ? Theme.Colors.success
                                                 : Theme.Colors.tertiaryText)
                VStack(alignment: .leading, spacing: 2) {
                    Text(currentSSID.isEmpty ? lang.s("wifi.unknown") : currentSSID)
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Text(node.telemetry?.ip ?? "")
                        .font(Theme.Typography.caption.monospacedDigit())
                        .foregroundColor(Theme.Colors.tertiaryText)
                }
                Spacer(minLength: 0)
            }
            .sandyCard()
        }
    }

    // ── الحقول ───────────────────────────────────────────────────────────────

    private var form: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            SectionHeader(title: lang.s("wifi.new"))

            TextField(lang.s("wifi.ssid"), text: $ssid)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()

            SecureField(lang.s("wifi.password"), text: $password)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()

            switch phase {
            case .trying(let left):
                HStack(spacing: Theme.Spacing.sm) {
                    ProgressView().tint(Theme.Colors.accent)
                    Text(String(format: lang.s("wifi.trying"), left))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
            default:
                SandyButton(title: lang.s("wifi.send"),
                            systemImage: "wifi", fillWidth: true) {
                    Task { await send() }
                }
                .disabled(ssid.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    private var safetyNote: some View {
        // مكتوبة قبل الزرّ مش بعده: القارئ لازم يعرف إنه في رجوع تلقائي وهو
        // بيقرّر، مش وهو بيستنى.
        SandyNotice(lang.s("wifi.safety"), kind: .info)
    }

    // ── الإرسال ثم الانتظار ──────────────────────────────────────────────────

    private func send() async {
        notice = ""
        let target = ssid.trimmingCharacters(in: .whitespaces)
        var window = 35
        do {
            window = try await state.api.switchNodeWiFi(
                nodeId: node.nodeId, ssid: target, password: password)
        } catch {
            notice = lang.s("wifi.sendFailed")
            return
        }

        // العدّ التنازلي حقيقي مش زينة: اللوح فعلًا مشغول بالتجربة، وبعده
        // بيرجع لحاله. إخفاء الانتظار بيخلّي المستخدم يعيد الإرسال بالنص —
        // وهاد بيرجّع اللوح لنقطة الصفر كل مرّة.
        for left in stride(from: window, through: 1, by: -1) {
            phase = .trying(secondsLeft: left)
            try? await Task.sleep(nanoseconds: 1_000_000_000)
        }

        await onFinished()

        // النتيجة من النبضة: الاسم اللي بيرجّعه اللوح هو اللي هو عليه فعلًا.
        let now: String = node.telemetry?.ssid ?? ""
        let ok: Bool = now == target
        phase = .done(success: ok)
        notice = ok ? "" : lang.s("wifi.rolledBack")
        if ok { dismiss() }
    }
}
