import SwiftUI
import WebKit

/// عين ساندي — مكان تشوف فيه، مش أزرار وبس.
///
/// ليش هاي الشاشة موجودة: كان في زرّ «التقط صورة» وزرّ «بث»، والتنين بيشتغلوا
/// تمام — الأمر بيوصل، والكاميرا بتصوّر، والصورة بترجع ع الخادم... وبتنرمى،
/// لأنه ولا حدا كان مستنيها. زرّ بيشتغل مضبوط وما بيوريك إشي مش ميزة.
///
/// وفي طريقتين للنظر، ولكل وحدة مكانها:
///
/// **صورة وحدة** بتمشي عبر الخادم: الكاميرا بتبعتها مقطّعة ع الوسيط، الخادم
/// بيجمّعها ويرجّعها. بتشتغل من أي مكان بالدنيا، وبتاخد ثواني.
///
/// **البث** بيمشي مباشرة من الكاميرا لجهازك ع الشبكة المحلية. فوري، بس بيشتغل
/// وإنت بالبيت بس — الكاميرا خادم صغير ع الشبكة، مش خدمة سحابية. وعنوانها
/// بيجي مع نبضتها، فما في تخمين ولا مسح شبكة.
struct CameraView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    let node: NodeItem

    @State private var photo: UIImage?
    @State private var taking = false
    @State private var notice = ""
    @State private var streaming = false
    @State private var starting = false

    /// عنوان الكاميرا ع الشبكة المحلية، من نبضتها هي.
    ///
    /// `camIP` مش `ip`: اللوحين بيشاركوا معرّف الوحدة، و`ip` كان بينقلب بينهم
    /// كل خمس ثواني — فالبثّ كان بيوجّه ع الدماغ نص الوقت، والدماغ ما عنده
    /// خادم صور. فشل مرّة من كل مرّتين بلا سبب ظاهر.
    private var localIP: String { node.telemetry?.camIP ?? "" }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.section) {
                stillSection
                streamSection
                Color.clear.frame(height: Theme.Spacing.xl)
            }
            .padding(Theme.Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .navigationTitle(lang.s("robot.control.camera.title"))
    }

    // ── صورة وحدة ────────────────────────────────────────────────────────────

    private var stillSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            SectionHeader(title: lang.s("robot.control.camera.still"))
            Text(lang.s("robot.control.camera.still.hint"))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)

            ZStack {
                RoundedRectangle(cornerRadius: Theme.Radius.card)
                    .fill(Theme.Colors.surface)
                    .aspectRatio(4.0 / 3.0, contentMode: .fit)

                if let photo {
                    Image(uiImage: photo)
                        .resizable()
                        .scaledToFit()
                        .cornerRadius(Theme.Radius.card)
                } else if taking {
                    VStack(spacing: Theme.Spacing.sm) {
                        ProgressView().tint(Theme.Colors.accent)
                        Text(lang.s("robot.control.camera.taking"))
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                } else {
                    Image(systemName: "camera")
                        .font(.system(size: Theme.Icon.xl))
                        .foregroundColor(Theme.Colors.tertiaryText)
                }
            }

            SandyButton(title: lang.s(taking ? "robot.control.camera.taking" : "robot.control.camera.take"),
                        systemImage: "camera.fill",
                        fillWidth: true) {
                Task { await take() }
            }
            .disabled(taking)

            if !notice.isEmpty {
                SandyNotice(notice, kind: .gentleWarning)
            }
        }
    }

    private func take() async {
        taking = true
        notice = ""
        defer { taking = false }
        do {
            let data = try await state.api.cameraSnapshot(nodeId: node.nodeId)
            guard let image = UIImage(data: data) else {
                notice = lang.s("robot.control.camera.badImage")
                return
            }
            photo = image
        } catch {
            notice = lang.s("robot.control.camera.failed")
        }
    }

    // ── البث ─────────────────────────────────────────────────────────────────

    @ViewBuilder
    private var streamSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            SectionHeader(title: lang.s("robot.control.camera.stream"))
            Text(lang.s("robot.control.camera.stream.hint"))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)

            if localIP.isEmpty {
                // ما وصلنا عنوانها بعد. نقولها بدل ما نعرض مربّع أسود بيبيّن
                // كأن البث خربان.
                SandyNotice(lang.s("robot.control.camera.stream.noAddress"), kind: .gentleWarning)
            } else if streaming {
                // **المحلي أولًا، والبعيد لمّا ما توصله.**
                //
                // المحلي بيمشي من الكاميرا لتلفونك مباشرة: سلس وبلا تأخير،
                // وبس وإنت ببيتك. والبعيد بيمرق ع الخادم: أبطأ، وبيشتغل من أي
                // مكان.
                //
                // والاختيار مش عليك. كنّا منعرض المحلي دايمًا، فالمستخدم برّا
                // البيت بيشوف مربّعًا فاضيًا ويفكّر إنّ الكاميرا خربانة — وهي
                // شغّالة، بس ع عنوان ما بيوصله من هناك.
                LiveView(localIP: localIP, nodeId: node.nodeId)
                    .environmentObject(state)
                    .aspectRatio(4.0 / 3.0, contentMode: .fit)
                    .cornerRadius(Theme.Radius.card)
                SandyButton(title: lang.s("robot.control.camera.stream.stop"),
                            systemImage: "stop.fill", fillWidth: true) {
                    Task { await stopStream() }
                }
            } else {
                SandyButton(title: lang.s(starting ? "robot.control.camera.stream.starting"
                                                   : "robot.control.camera.stream.start"),
                            systemImage: "play.fill", fillWidth: true) {
                    Task { await startStream() }
                }
                .disabled(starting)
                Text(String(format: lang.s("robot.control.camera.stream.address"), localIP))
                    .font(Theme.Typography.caption.monospacedDigit())
                    .foregroundColor(Theme.Colors.tertiaryText)
            }
        }
    }

    /// **يقول للّوح يشغّل خادمه، وبعدين بس بيفتح العارض.**
    ///
    /// الزرّ كان بيعمل `streaming = true` وبس. والكاميرا ما بتشغّل خادم الـ HTTP
    /// إلا لمّا ينطلب منها — نبضتها كانت بتقول `stream:false` بكل مرّة. فالعارض
    /// كان بيفتح ع عنوان ما في حدا سامع عليه، والويب-فيو بيعرض علامة استفهام:
    /// مربّع مكسور، بيبيّن كأنّ الشبكة غلط أو الجهاز بعيد.
    ///
    /// وهاي أسوأ صيغة للعطل — العرض بيتّهم شغلة سليمة (الشبكة) عن شغلة ما
    /// انعملت أصلًا (الأمر). المالك بيروح يفحص راوتره وهو مضبوط.
    private func startStream() async {
        starting = true
        notice = ""
        defer { starting = false }
        do {
            try await state.api.controlDevice(name: "cam_stream", action: "on")
            // اللوح بده لحظة يرفع الخادم. فتح العارض بنفس الثانية بيعطي نفس
            // المربّع المكسور، والمستخدم ما بيفرّق بين «لسا» و«ما زبط».
            try? await Task.sleep(nanoseconds: 1_200_000_000)
            streaming = true
        } catch {
            notice = lang.s("robot.control.camera.stream.failed")
        }
    }

    /// وإطفاؤه لمّا نخلص — مش تجميل.
    ///
    /// خادم الـ HTTP بيضل شغّال ع اللوح لحدّ ما ينطلب يوقف. لوح صغير ببث دائم
    /// بيسخن وبياكل كهربا وبيبطّئ كل إشي تاني عليه — ومنها الالتقاط.
    private func stopStream() async {
        streaming = false
        try? await state.api.controlDevice(name: "cam_stream", action: "off")
    }
}

/// البثّ — محلي لو الكاميرا قريبة، وعبر الخادم لو بعيدة.
///
/// بتجرّب المحلي أول لأنه أحسن بكل مقياس: بلا تأخير، وبمعدّل إطارات كامل، وما
/// بيكلّف نطاقًا ع الخادم. وإذا ما ردّ خلال ثانيتين — يعني إنت برّا البيت —
/// بتحوّل للبعيد بلا ما تسأل المستخدم.
///
/// **والتحويل بيصير مرّة وحدة وبيثبت.** لو ضلّت تجرّب المحلي بين إطار وإطار،
/// بتصير الصورة بتقطّع كل مرّة، والمستخدم بيشوف بثًّا مكسورًا بدل بثّ بعيد.
private struct LiveView: View {
    @EnvironmentObject var state: AppState
    let localIP: String
    let nodeId: String

    @State private var mode: Mode = .probing
    @State private var frame: UIImage?

    private enum Mode { case probing, local, remote }

    var body: some View {
        Group {
            switch mode {
            case .local:
                MJPEGView(url: URL(string: "http://\(localIP)/stream"))
            case .remote:
                if let frame {
                    Image(uiImage: frame).resizable().scaledToFit()
                } else {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            case .probing:
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task { await decideAndRun() }
    }

    private func decideAndRun() async {
        mode = await reachable() ? .local : .remote
        guard mode == .remote else { return }
        // ثلاثة بالثانية — نفس وتيرة رفع اللوح. أسرع منها بيسحب نفس الإطار
        // مرّتين وبيستهلك بيانات بلا فايدة.
        while !Task.isCancelled {
            if let d = try? await state.api.liveFrame(nodeId: nodeId),
               let img = UIImage(data: d) {
                frame = img
            }
            try? await Task.sleep(nanoseconds: 330_000_000)
        }
    }

    /// هل الكاميرا موصولة من هون؟ سؤال بمهلة قصيرة — الجواب «لأ» بييجي بسرعة
    /// ع شبكة تانية، والمستخدم ما بيستنّى عشان يعرف إنه برّا البيت.
    private func reachable() async -> Bool {
        guard !localIP.isEmpty,
              let url = URL(string: "http://\(localIP)/") else { return false }
        var req = URLRequest(url: url)
        req.timeoutInterval = 2
        req.httpMethod = "HEAD"
        // The robot on the local network, not the backend — so it keeps the
        // shared session deliberately: `waitsForConnectivity` would hold a
        // reachability probe open instead of answering "not reachable", which
        // is the one thing this call exists to find out.
        return (try? await URLSession.shared.data(for: req)) != nil
    }
}

/// عارض MJPEG بسيط فوق WKWebView.
///
/// البث اللي بتبعته الكاميرا هو `multipart/x-mixed-replace` — الصيغة اللي كل
/// متصفّح بيعرفها من عشرين سنة، وما في مشغّل جاهز بـ SwiftUI بيفهمها. كتابة
/// فاكّ لها بالإيد يعني قراءة الحدود وفكّ كل إطار وإدارة الاتصال؛ الويب-فيو
/// بيعمل هاد كله وهو مختبَر أكتر من أي إشي ممكن أكتبه.
///
/// ما بيمرق ع السحابة: الرابط عنوان محلي، فالبث بيروح من الكاميرا لجهازك
/// مباشرة. سريع، وبيشتغل وإنت بالبيت بس — وهاي حقيقة الشبكة مش قرار.
private struct MJPEGView: UIViewRepresentable {
    let url: URL?

    func makeUIView(context: Context) -> WKWebView {
        let view = WKWebView()
        view.isOpaque = false
        view.backgroundColor = .black
        view.scrollView.isScrollEnabled = false
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        guard let url else { return }
        // صفحة صغيرة بتحطّ الصورة بالنص وتملا الإطار — أبسط من التحكّم بحجم
        // الصورة من جوا الويب-فيو.
        let html = """
        <html><head><meta name="viewport" content="width=device-width,\
        initial-scale=1"><style>html,body{margin:0;height:100%;background:#000;\
        display:flex;align-items:center;justify-content:center}\
        img{max-width:100%;max-height:100%}</style></head>\
        <body><img src="\(url.absoluteString)"></body></html>
        """
        view.loadHTMLString(html, baseURL: url)
    }
}
