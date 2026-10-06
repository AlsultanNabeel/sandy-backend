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
    /// The sentence for why no photo came: a known reason has its own, the rest the general one.
    static func errorKey(_ code: String) -> String {
        let known = ["camera_init_failed_at_boot", "capture_failed", "upload_failed",
                     "camera_busy", "camera_offline"]
        return known.contains(code) ? "robot.control.camera.error.\(code)" : "robot.control.camera.failed"
    }

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
    private var streamKey: String { node.telemetry?.camStreamKey ?? "" }

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
                        LoadingDots()
                        Text(lang.s("robot.control.camera.taking"))
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                } else {
                    Image(systemName: "camera")
                        .scaledFont(Theme.Icon.xl, relativeTo: .largeTitle)
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
            // الكاميرا صارت تقول ليش ما في صورة. سبب معروف بجملته، والباقي
            // بالجملة العامة.
            notice = lang.s(Self.errorKey((error as? APIError)?.code ?? ""))
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

            // **البعيد ما بيحتاج عنوانًا محليًّا.** كان الشرط هون «ما في عنوان ←
            // ما في بث»، فكاميرا لسا ما بعتت عنوانها — أو إنت برّا البيت أصلًا —
            // ما كانت تعرض زرّ البث ولا مرّة، مع إنّ البث عبر الخادم ما إله علاقة
            // بالعنوان. `LiveView` بيقرّر: محلي لو وصلّه، بعيد غير هيك.
            if streaming {
                // **المحلي أولًا، والبعيد لمّا ما توصله.**
                //
                // المحلي بيمشي من الكاميرا لتلفونك مباشرة: سلس وبلا تأخير،
                // وبس وإنت ببيتك. والبعيد بيمرق ع الخادم: أبطأ، وبيشتغل من أي
                // مكان.
                //
                // والاختيار مش عليك. كنّا منعرض المحلي دايمًا، فالمستخدم برّا
                // البيت بيشوف مربّعًا فاضيًا ويفكّر إنّ الكاميرا خربانة — وهي
                // شغّالة، بس ع عنوان ما بيوصله من هناك.
                LiveView(localIP: localIP, streamKey: streamKey, nodeId: node.nodeId)
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
                if !localIP.isEmpty {
                    Text(String(format: lang.s("robot.control.camera.stream.address"), localIP))
                        .font(Theme.Typography.caption.monospacedDigit())
                        .foregroundColor(Theme.Colors.tertiaryText)
                }
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

/// When a remote stream counts as stopped: frames come about three a second, so ten seconds
/// with none is not a slow link.
enum StreamWatch {
    static let stalledAfter: TimeInterval = 10

    static func stalled(lastFrameAt: Date?, now: Date) -> Bool {
        guard let lastFrameAt else { return false }
        return now.timeIntervalSince(lastFrameAt) > stalledAfter
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
    let streamKey: String
    let nodeId: String

    @State private var mode: Mode = .probing

    /// عنوان محلي بالمفتاح. الكاميرا بترفض أي طلب بلاه.
    private func localURL(_ path: String) -> URL? {
        guard !localIP.isEmpty, !streamKey.isEmpty else { return nil }
        var c = URLComponents()
        c.scheme = "http"
        c.host = localIP
        c.path = path
        c.queryItems = [URLQueryItem(name: "key", value: streamKey)]
        return c.url
    }
    @State private var frame: UIImage?
    /// Why no picture is coming (the camera is off, or nothing arrived in time): said, not a
    /// placeholder that spins for ever.
    @State private var problem: String?

    private enum Mode { case probing, local, remote }
    /// No frame this long and the wait is reported.
    private static let noFrameAfter: TimeInterval = 10

    var body: some View {
        Group {
            switch mode {
            case .local:
                MJPEGView(url: localURL("/stream"))
            case .remote:
                if let frame {
                    Image(uiImage: frame).resizable().scaledToFit()
                } else if let problem {
                    SandyNotice(problem, kind: .gentleWarning)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    SkeletonBlock().frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            case .probing:
                SkeletonBlock().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task { await decideAndRun() }
    }

    private func decideAndRun() async {
        mode = await reachable() ? .local : .remote
        guard mode == .remote else { return }
        // ثلاثة بالثانية — نفس وتيرة رفع اللوح. أسرع منها بيسحب نفس الإطار
        // مرّتين وبيستهلك بيانات بلا فايدة.
        let started = Date()
        var lastFrameAt: Date?
        while !Task.isCancelled {
            do {
                if let d = try await state.api.liveFrame(nodeId: nodeId),
                   let img = UIImage(data: d) {
                    frame = img
                    lastFrameAt = Date()
                    problem = nil
                } else if frame == nil, Date().timeIntervalSince(started) > Self.noFrameAfter {
                    problem = LanguageManager.shared.s("robot.control.camera.noFrames")
                } else if StreamWatch.stalled(lastFrameAt: lastFrameAt, now: Date()) {
                    // The last picture is not live any more: say the stream stopped.
                    frame = nil
                    problem = LanguageManager.shared.s("robot.control.camera.streamStopped")
                }
            } catch where error.isCancellation {
                return
            } catch {
                // Said once, then asked again slowly: it comes back when the camera does.
                problem = error.localizedDescription
                frame = nil
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
            try? await Task.sleep(nanoseconds: 330_000_000)
        }
    }

    /// هل الكاميرا موصولة من هون؟ سؤال بمهلة قصيرة — الجواب «لأ» بييجي بسرعة
    /// ع شبكة تانية، والمستخدم ما بيستنّى عشان يعرف إنه برّا البيت.
    private func reachable() async -> Bool {
        // `/status` بالمفتاح: «ردّ» ما عاد بيكفّي — لازم يردّ **بنعم**. قبل،
        // أي جواب (حتى «مش موجود») كان بيعدّ وصولًا، فراوتر تاني ع نفس العنوان
        // بشبكة تانية كان بيخلّي التطبيق يفتح بثًّا محليًّا ع جهاز غلط.
        guard let url = localURL("/status") else { return false }
        var req = URLRequest(url: url)
        req.timeoutInterval = 2
        // The robot on the local network, not the backend — so it keeps the
        // shared session deliberately: `waitsForConnectivity` would hold a
        // reachability probe open instead of answering "not reachable", which
        // is the one thing this call exists to find out.
        guard let (_, resp) = try? await URLSession.shared.data(for: req) else { return false }
        return (resp as? HTTPURLResponse)?.statusCode == 200
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
