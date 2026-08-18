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

    /// أي لوح — الدماغ ولا الكاميرا.
    ///
    /// اللوحان تحت معرّف وحدة واحد بالتصميم، فـ«انقل ساندي» جملة ناقصة لمّا
    /// يكونوا ع شبكتين. والاختيار صريح مش مخفي: نقل الاتنين سوا معناه إنه غلطة
    /// وحدة بتوقّف التنين، وهاد بيضيّع الفائدة الأساسية — إنه واحد بيضل واصل
    /// ويقولك شو صار للتاني.
    @State private var board: String = "brain"
    @State private var ssid = ""
    @State private var password = ""
    @State private var phase: Phase = .idle
    @State private var notice = ""

    private enum Phase: Equatable {
        case idle
        case trying(secondsLeft: Int)
        case done(success: Bool)
    }

    private var currentSSID: String {
        board == "camera" ? (node.telemetry?.camSSID ?? "")
                          : (node.telemetry?.ssid ?? "")
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.section) {
                boardPicker
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

    private var boardPicker: some View {
        Picker("", selection: $board) {
            Text(lang.s("wifi.board.brain")).tag("brain")
            Text(lang.s("wifi.board.camera")).tag("camera")
        }
        .pickerStyle(.segmented)
        .disabled(phase != .idle)
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

    /// السبب اللي رجّعه الخادم، بجملة مفهومة.
    ///
    /// الأكواد بتيجي زي ما هي من `wifi_switch.py`. أي كود مش معروف بينعرض زي ما
    /// هو بدل ما ينستبدل بجملة عامة: كود غريب ع الشاشة بتقدر تبعتلي إياه، وجملة
    /// عامة بتخفيه.
    private func reason(from error: Error) -> String {
        guard let api = error as? APIError else { return lang.s("wifi.sendFailed") }
        switch api.kind {
        case .connection:  return lang.s("wifi.err.offline")
        case .unauthorized: return lang.s("wifi.err.session")
        default: break
        }
        switch api.message {
        case "not_yours": return lang.s("wifi.err.notYours")
        case "not_sent":  return lang.s("wifi.err.notSent")
        case "no_node":   return lang.s("wifi.err.noNode")
        case "bad_board": return lang.s("wifi.err.badBoard")
        case "too_long":  return lang.s("wifi.err.tooLong")
        case "bad_chars": return lang.s("wifi.err.badChars")
        default:          return api.message
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
                nodeId: node.nodeId, ssid: target, password: password, board: board)
        } catch {
            // **بنعرض سبب الخادم، مش تخمين.**
            //
            // كانت هون رسالة وحدة: «تأكّد إنك متصل». والخادم بيرجّع سببًا
            // محدّدًا — الوحدة مش إلك، الوسيط ما استقبل، اللوح مش معروف — فكنّا
            // نرميه ونحطّ مكانه اتهامًا للنت. المالك بيروح يفحص راوتره وهو
            // شغّال، والسبب الحقيقي مكتوب وانرمى.
            notice = reason(from: error)
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
        let now: String = currentSSID
        let ok: Bool = now == target
        phase = .done(success: ok)
        notice = ok ? "" : lang.s("wifi.rolledBack")
        if ok { dismiss() }
    }
}
