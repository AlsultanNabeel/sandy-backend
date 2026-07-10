import SwiftUI

// MARK: - SandyRobot — وجه/جسم ساندي الروبوت (منقول من RobotFace.jsx بالويب)
//
//  نسخة SwiftUI أمينة من روبوت ساندي SVG (viewBox 110×172، أزرق كهربائي #00D4FF).
//  نرسمها داخل Canvas مقيّس بـ size/110 عشان تظل حادّة بأي حجم (أفاتار 28–40،
//  أو بطل 96+). كل الإحداثيات بنفس مرجع الويب (عينان عند 34,57 و 76,57).
//
//  الواجهة العامة (ملفات ثانية تعتمد عليها — لا تغيّر التواقيع):
//      SandyRobot(size:gaze:blink:happy:animated:)
//
//  - size      : العرض المرسوم بالنقاط؛ الارتفاع = size * 172/110.
//  - gaze      : إزاحة البؤبؤ بوحدات الـ viewBox (~ -8...8).
//  - blink     : تغمّض العينين (قوس جفن مغلق) بدل البؤبؤ.
//  - happy     : يقوّس الفم لأعلى (ابتسامة) بدل الخط الهادئ.
//  - animated  : يشغّل غمزة دورية لطيفة + انجراف بطيء بسيط للنظرة.
//
//  iOS 16-safe: Canvas الأساسي + TimelineView(.animation) فقط، بدون أي API أحدث.

struct SandyRobot: View {
    var size: CGFloat = 80          // العرض المرسوم؛ الارتفاع = size * 172/110
    var gaze: CGSize = .zero        // إزاحة البؤبؤ بوحدات الـ viewBox (~ -8...8)
    var blink: Bool = false
    var happy: Bool = false
    var animated: Bool = true       // غمزة تلقائية + انجراف نظرة خفيف
    var mouthOpen: CGFloat = 0      // انفتاح الفم (صفر..واحد) — يحرّكه الصوت أثناء الكلام

    // أبعاد الـ viewBox الأصلي (110×172).
    private let vbW: CGFloat = 110
    private let vbH: CGFloat = 172

    private var renderedHeight: CGFloat { size * (vbH / vbW) }

    var body: some View {
        Group {
            if animated {
                // ساعة موحّدة تقود الغمزة الدورية وانجراف النظرة (iOS 16-safe).
                TimelineView(.animation) { timeline in
                    let t = timeline.date.timeIntervalSinceReferenceDate
                    robotCanvas(autoBlink: autoBlink(at: t),
                                drift: idleDrift(at: t))
                }
            } else {
                robotCanvas(autoBlink: false, drift: .zero)
            }
        }
        .frame(width: size, height: renderedHeight)
        // هالة كهربائية ناعمة حولها (تقابل blue glow بالويب).
        .shadow(color: Theme.Shadow.glowColor, radius: size * 0.10, x: 0, y: 0)
        .accessibilityLabel("ساندي")
    }

    // MARK: حركة (iOS 16-safe — مشتقّة من الزمن، بدون مؤقّتات منفصلة)

    /// غمزة دورية: كل ~3.5s تغمّض ~0.12s.
    private func autoBlink(at time: TimeInterval) -> Bool {
        let cycle: Double = 3.5
        let phase = time.truncatingRemainder(dividingBy: cycle)
        return phase >= (cycle - 0.12)
    }

    /// انجراف نظرة بطيء وخفيف: دوائر ليساجو لطيفة ضمن ~±3 وحدات viewBox.
    private func idleDrift(at time: TimeInterval) -> CGSize {
        let dx = sin(time * 0.45) * 3.0
        let dy = cos(time * 0.30) * 2.0 + 1.5   // ميل بسيط لأسفل (مثل الويب gaze.y≈3)
        return CGSize(width: dx, height: dy)
    }

    // MARK: الرسم

    private func robotCanvas(autoBlink: Bool, drift: CGSize) -> some View {
        let isBlinking = blink || autoBlink
        // النظرة النهائية = نظرة ممرّرة + انجراف خمول (محصورة ضمن مدى معقول).
        let gx = clampGaze(gaze.width + drift.width)
        let gy = clampGaze(gaze.height + drift.height)

        return Canvas { ctx, canvasSize in
            // مقياس من الـ viewBox (110×172) إلى الإطار الفعلي.
            let scale = canvasSize.width / self.vbW
            ctx.scaleBy(x: scale, y: scale)
            self.draw(in: &ctx, blinking: isBlinking, gx: gx, gy: gy)
        }
    }

    private func clampGaze(_ v: CGFloat) -> CGFloat {
        min(max(v, -8), 8)
    }

    /// لون الأزرق الكهربائي بشفافية a (تقابل rgba(0,212,255,a) بالويب).
    private func cyan(_ a: Double) -> Color { Theme.Colors.accent.opacity(a) }

    // كل الرسم بإحداثيات الـ viewBox (110×172)؛ الـ Canvas مقيّس مسبقًا.
    private func draw(in ctx: inout GraphicsContext, blinking: Bool, gx: CGFloat, gy: CGFloat) {
        let LX: CGFloat = 34, LY: CGFloat = 57
        let RX: CGFloat = 76, RY: CGFloat = 57

        // ── ظل قاعدة بيضوي خافت تحتها ─────────────────────────────────
        let baseRect = CGRect(x: 55 - 32, y: 169, width: 64, height: 8)
        let basePath = Path(ellipseIn: baseRect)
        ctx.fill(basePath, with: .radialGradient(
            Gradient(colors: [cyan(0.32), cyan(0.06), .clear]),
            center: CGPoint(x: 55, y: 173),
            startRadius: 0, endRadius: 34))

        // ── الذراعان (مستطيلات مدوّرة) ────────────────────────────────
        drawRoundedRect(&ctx, x: 2,  y: 108, w: 16, h: 35, r: 8,
                        fill: cyan(0.04), stroke: cyan(0.36), lineWidth: 1.5)
        drawRoundedRect(&ctx, x: 92, y: 108, w: 16, h: 35, r: 8,
                        fill: cyan(0.04), stroke: cyan(0.36), lineWidth: 1.5)

        // ── الهوائي (خط + ✦ متوهّجة) ──────────────────────────────────
        var antenna = Path()
        antenna.move(to: CGPoint(x: 55, y: 8))
        antenna.addLine(to: CGPoint(x: 55, y: 24))
        ctx.stroke(antenna, with: .color(cyan(0.45)),
                   style: StrokeStyle(lineWidth: 1.5, lineCap: .round))
        let spark = Text("✦")
            .font(.system(size: 11))
            .foregroundColor(cyan(0.85))
        // توهّج بسيط بطبقة مكرّرة خلف العلامة.
        var glowCtx = ctx
        glowCtx.addFilter(.blur(radius: 1.6))
        glowCtx.draw(spark, at: CGPoint(x: 55, y: 8), anchor: .center)
        ctx.draw(spark, at: CGPoint(x: 55, y: 8), anchor: .center)

        // ── الرأس (مستطيل مدوّر r=22) ─────────────────────────────────
        drawRoundedRect(&ctx, x: 10, y: 24, w: 90, h: 76, r: 22,
                        fill: Color(red: 0, green: 8/255, blue: 20/255).opacity(0.55),
                        stroke: cyan(0.5), lineWidth: 1.5)

        // ── حاجبان ────────────────────────────────────────────────────
        let brow = Color(red: 200/255, green: 240/255, blue: 1.0).opacity(0.65)
        drawRoundedRect(&ctx, x: 18, y: 33, w: 26, h: 3, r: 1.5, fill: brow, stroke: nil, lineWidth: 0)
        drawRoundedRect(&ctx, x: 66, y: 33, w: 26, h: 3, r: 1.5, fill: brow, stroke: nil, lineWidth: 0)

        // ── محجرا العينين ─────────────────────────────────────────────
        drawEyeSocket(&ctx, cx: LX, cy: LY)
        drawEyeSocket(&ctx, cx: RX, cy: RY)

        // ── العينان (بؤبؤ أو جفن مغلق) ────────────────────────────────
        if blinking {
            drawClosedEye(&ctx, x: LX, y: LY)
            drawClosedEye(&ctx, x: RX, y: RY)
        } else {
            drawPupil(&ctx, cx: LX, cy: LY, gx: gx, gy: gy)
            drawPupil(&ctx, cx: RX, cy: RY, gx: gx, gy: gy)
        }

        // ── الفم ──────────────────────────────────────────────────────
        // وهي تحكي (mouthOpen > 0) ينفتح الفم كبيضوي يكبر/يصغر على الموجة؛
        // وإلا ابتسامة (happy) أو خط هادئ.
        if mouthOpen > 0.06 {
            let open = min(max(mouthOpen, 0), 1)
            let h = 3 + open * 13          // ارتفاع الفتحة 3..16
            let w = 26 - open * 5          // يضيق شوي وهو ينفتح
            let rect = CGRect(x: 55 - w / 2, y: 89 - h / 2, width: w, height: h)
            let cavity = Path(roundedRect: rect, cornerRadius: min(w, h) / 2, style: .continuous)
            ctx.fill(cavity, with: .color(Color(red: 0, green: 5/255, blue: 18/255).opacity(0.92)))
            ctx.stroke(cavity, with: .color(cyan(0.55)), style: StrokeStyle(lineWidth: 2.5))
        } else if happy {
            var mouth = Path()
            mouth.move(to: CGPoint(x: 40, y: 88))
            mouth.addQuadCurve(to: CGPoint(x: 70, y: 88), control: CGPoint(x: 55, y: 96))
            ctx.stroke(mouth, with: .color(cyan(0.55)),
                       style: StrokeStyle(lineWidth: 3, lineCap: .round))
        } else {
            drawRoundedRect(&ctx, x: 40, y: 88, w: 30, h: 3, r: 1.5,
                            fill: cyan(0.35), stroke: nil, lineWidth: 0)
        }

        // ── الجسم ─────────────────────────────────────────────────────
        var body = Path()
        body.move(to: CGPoint(x: 25, y: 106))
        body.addQuadCurve(to: CGPoint(x: 22, y: 140), control: CGPoint(x: 16, y: 122))
        body.addQuadCurve(to: CGPoint(x: 55, y: 155), control: CGPoint(x: 28, y: 155))
        body.addQuadCurve(to: CGPoint(x: 88, y: 140), control: CGPoint(x: 82, y: 155))
        body.addQuadCurve(to: CGPoint(x: 85, y: 106), control: CGPoint(x: 94, y: 122))
        body.addQuadCurve(to: CGPoint(x: 55, y: 101), control: CGPoint(x: 74, y: 101))
        body.addQuadCurve(to: CGPoint(x: 25, y: 106), control: CGPoint(x: 36, y: 101))
        body.closeSubpath()
        ctx.fill(body, with: .color(cyan(0.025)))
        ctx.stroke(body, with: .color(cyan(0.42)), style: StrokeStyle(lineWidth: 1.5))

        // اسم "SANDY" متوهّج خفيف.
        let nameText = Text("SANDY")
            .font(.system(size: 11, weight: .bold))
            .tracking(3)
            .foregroundColor(cyan(0.75))
        var nameGlow = ctx
        nameGlow.addFilter(.blur(radius: 1.4))
        nameGlow.draw(nameText, at: CGPoint(x: 55, y: 127), anchor: .center)
        ctx.draw(nameText, at: CGPoint(x: 55, y: 127), anchor: .center)

        // خط رفيع تحت الاسم.
        var underline = Path()
        underline.move(to: CGPoint(x: 36, y: 132))
        underline.addLine(to: CGPoint(x: 74, y: 132))
        ctx.stroke(underline, with: .color(cyan(0.12)), style: StrokeStyle(lineWidth: 0.8))

        // ── الساقان ───────────────────────────────────────────────────
        drawRoundedRect(&ctx, x: 28, y: 157, w: 23, h: 14, r: 7,
                        fill: cyan(0.025), stroke: cyan(0.36), lineWidth: 1.5)
        drawRoundedRect(&ctx, x: 59, y: 157, w: 23, h: 14, r: 7,
                        fill: cyan(0.025), stroke: cyan(0.36), lineWidth: 1.5)
    }

    // MARK: مساعدات الرسم

    /// مستطيل مدوّر بتعبئة و/أو حدّ (إحداثيات viewBox).
    private func drawRoundedRect(_ ctx: inout GraphicsContext,
                                 x: CGFloat, y: CGFloat, w: CGFloat, h: CGFloat, r: CGFloat,
                                 fill: Color?, stroke: Color?, lineWidth: CGFloat) {
        let path = Path(roundedRect: CGRect(x: x, y: y, width: w, height: h),
                        cornerRadius: r, style: .continuous)
        if let fill {
            ctx.fill(path, with: .color(fill))
        }
        if let stroke {
            ctx.stroke(path, with: .color(stroke), style: StrokeStyle(lineWidth: lineWidth))
        }
    }

    /// محجر العين: دائرة خارجية معتمة بحدّ متوهّج + قزحية بتدرّج شعاعي.
    private func drawEyeSocket(_ ctx: inout GraphicsContext, cx: CGFloat, cy: CGFloat) {
        // الخارجية (r=18) — تعبئة معتمة + حدّ سماوي + توهّج.
        let outerRect = CGRect(x: cx - 18, y: cy - 18, width: 36, height: 36)
        let outer = Path(ellipseIn: outerRect)
        // توهّج: حدّ مكرّر بطبقة مموّهة.
        var glow = ctx
        glow.addFilter(.blur(radius: 2.6))
        glow.stroke(outer, with: .color(cyan(0.88)), style: StrokeStyle(lineWidth: 2.5))
        ctx.fill(outer, with: .color(Color(red: 0, green: 12/255, blue: 30/255).opacity(0.88)))
        ctx.stroke(outer, with: .color(cyan(0.88)), style: StrokeStyle(lineWidth: 2.5))

        // القزحية (r=15) — تدرّج شعاعي مزاح للأعلى-اليسار (cx 40%, cy 35%).
        let irisRect = CGRect(x: cx - 15, y: cy - 15, width: 30, height: 30)
        let iris = Path(ellipseIn: irisRect)
        let gradient = Gradient(stops: [
            .init(color: Color(red: 160/255, green: 235/255, blue: 1.0).opacity(0.85), location: 0.0),
            .init(color: Color(red: 0, green: 195/255, blue: 240/255).opacity(0.6), location: 0.45),
            .init(color: Color(red: 0, green: 120/255, blue: 190/255).opacity(0.2), location: 1.0),
        ])
        ctx.fill(iris, with: .radialGradient(
            gradient,
            center: CGPoint(x: cx - 3, y: cy - 4.5),   // ~ (40%,35%) ضمن r=15
            startRadius: 0, endRadius: 19.5))           // ~65% من قطر القزحية
        ctx.stroke(iris, with: .color(cyan(0.3)), style: StrokeStyle(lineWidth: 0.8))
    }

    /// البؤبؤ المفتوح: بيضوي داكن مزاح بالنظرة + لمعتان.
    private func drawPupil(_ ctx: inout GraphicsContext, cx: CGFloat, cy: CGFloat, gx: CGFloat, gy: CGFloat) {
        let pcx = cx + gx
        let pcy = cy + gy
        // البؤبؤ (rx=10, ry=9).
        let pupilRect = CGRect(x: pcx - 10, y: pcy - 9, width: 20, height: 18)
        let pupil = Path(ellipseIn: pupilRect)
        ctx.fill(pupil, with: .color(Color(red: 0, green: 5/255, blue: 18/255).opacity(0.92)))

        // لمعة كبيرة (r=5.5) عند (cx-8, cy-8) — تتبع محجر العين لا البؤبؤ.
        let bigRect = CGRect(x: (cx - 8) - 5.5, y: (cy - 8) - 5.5, width: 11, height: 11)
        ctx.fill(Path(ellipseIn: bigRect), with: .color(Color.white.opacity(0.82)))

        // لمعة صغيرة (r=1.8) عند (cx+6, cy+7).
        let smallRect = CGRect(x: (cx + 6) - 1.8, y: (cy + 7) - 1.8, width: 3.6, height: 3.6)
        ctx.fill(Path(ellipseIn: smallRect), with: .color(Color.white.opacity(0.26)))
    }

    /// عين مغمضة: قوس جفن `M (x-17) y Q x (y-8) (x+17) y`.
    private func drawClosedEye(_ ctx: inout GraphicsContext, x: CGFloat, y: CGFloat) {
        var lid = Path()
        lid.move(to: CGPoint(x: x - 17, y: y))
        lid.addQuadCurve(to: CGPoint(x: x + 17, y: y), control: CGPoint(x: x, y: y - 8))
        ctx.stroke(lid, with: .color(cyan(0.9)),
                   style: StrokeStyle(lineWidth: 3, lineCap: .round))
    }
}

#if DEBUG
struct SandyRobot_Previews: PreviewProvider {
    static var previews: some View {
        HStack(spacing: 24) {
            SandyRobot(size: 36, happy: true)
            SandyRobot(size: 80)
            SandyRobot(size: 120, gaze: CGSize(width: 6, height: -2), happy: true)
            SandyRobot(size: 80, blink: true, animated: false)
        }
        .padding(40)
        .background(Theme.Colors.background)
    }
}
#endif
