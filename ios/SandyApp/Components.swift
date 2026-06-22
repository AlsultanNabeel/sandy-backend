import SwiftUI

// MARK: - دليل الاستدعاء (لباقي الـ agents — وقّعوا المكوّنات بالضبط كذا)
//
//  مكوّنات ساندي القابلة لإعادة الاستخدام. كلها RTL-aware ومتوافقة iOS 16.
//
//  1) SandyButton — زر إجراء أساسي جميل (مرجاني، حواف، أيقونة + نص).
//     SandyButton(title: String,
//                 systemImage: String? = nil,
//                 style: SandyButton.Style = .primary,   // .primary | .secondary
//                 isLoading: Bool = false,
//                 fillWidth: Bool = false,
//                 action: () -> Void)
//     مثال:  SandyButton(title: "إضافة", systemImage: "plus") { add() }
//            SandyButton(title: "إلغاء", systemImage: nil, style: .secondary) { cancel() }
//
//  2) SandyCard — حاوية البطاقة القياسية (سطح + ظل + حواف).
//     SandyCard { content }                       // padding افتراضي
//     SandyCard(padding: CGFloat) { content }
//     مثال:  SandyCard { Text("محتوى") }
//
//  3) SandyNotice — تنبيه/خطأ دافئ بصوت ساندي (مو سطر أحمر).
//     SandyNotice(_ message: String,
//                 kind: SandyNotice.Kind = .info)   // .info | .gentleWarning
//     مثال:  SandyNotice("معلش، صار خطأ بسيط — جرّب كمان مرة.", kind: .gentleWarning)
//
//  4) FloatingSandy — رفيق ساندي العائم (overlay) مع فقاعة كلام اختيارية.
//     FloatingSandy(message: String? = nil,
//                   corner: FloatingSandy.Corner = .bottomTrailing,  // أو .bottomLeading
//                   onTap: (() -> Void)? = nil)
//     الاستعمال:  SomeView().overlay(alignment: .bottomTrailing) { FloatingSandy(message: "أهلين!") }
//                 أو بدون رسالة: FloatingSandy()
//
// ─────────────────────────────────────────────────────────────────────────

// MARK: - 1) SandyButton

/// زر إجراء أساسي بنمط ساندي: تعبئة مرجانية، حواف ناعمة، أيقونة + نص واضح.
/// له نمطان: أساسي (مملوء) وثانوي (محدّد). يدعم حالة تحميل.
struct SandyButton: View {
    enum Style { case primary, secondary }

    let title: String
    var systemImage: String? = nil
    var style: Style = .primary
    var isLoading: Bool = false
    var fillWidth: Bool = false
    let action: () -> Void

    init(title: String,
         systemImage: String? = nil,
         style: Style = .primary,
         isLoading: Bool = false,
         fillWidth: Bool = false,
         action: @escaping () -> Void) {
        self.title = title
        self.systemImage = systemImage
        self.style = style
        self.isLoading = isLoading
        self.fillWidth = fillWidth
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: Theme.Spacing.sm) {
                if isLoading {
                    ProgressView()
                        .progressViewStyle(.circular)
                        .tint(foreground)
                } else if let systemImage {
                    Image(systemName: systemImage)
                        .font(.system(size: 15, weight: .semibold))
                }
                Text(title)
                    .font(Theme.Typography.button)
            }
            .foregroundColor(foreground)
            .padding(.vertical, Theme.Spacing.md)
            .padding(.horizontal, Theme.Spacing.lg)
            .frame(maxWidth: fillWidth ? .infinity : nil)
            .background(background)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                    .stroke(borderColor, lineWidth: style == .secondary ? 1.5 : 0)
            )
            .shadow(color: style == .primary ? Theme.Shadow.glowColor : .clear,
                    radius: style == .primary ? 8 : 0, x: 0, y: 3)
        }
        .buttonStyle(.plain)
        .disabled(isLoading)
        .opacity(isLoading ? 0.85 : 1)
    }

    // ألوان حسب النمط
    private var foreground: Color {
        style == .primary ? Theme.Colors.onAccent : Theme.Colors.accentDeep
    }
    @ViewBuilder private var background: some View {
        switch style {
        case .primary:
            LinearGradient(
                colors: [Theme.Colors.accent, Theme.Colors.accentDeep],
                startPoint: .topLeading, endPoint: .bottomTrailing)
        case .secondary:
            // ثانوي = زجاج سائل: سطح مموّه + لمسة أزرق خفيفة.
            ZStack {
                Rectangle().fill(.ultraThinMaterial)
                Rectangle().fill(Theme.Colors.accent.opacity(0.08))
            }
        }
    }
    private var borderColor: Color {
        style == .secondary ? Theme.Colors.accent.opacity(0.35) : .clear
    }
}

// MARK: - 2) SandyCard

/// حاوية البطاقة القياسية: سطح أبيض + حواف + ظل خفيف + حدّ رفيع.
/// تلفّ أي محتوى — تستعمل بكل الواجهات بدل تكرار الخلفيات يدويًا.
struct SandyCard<Content: View>: View {
    var padding: CGFloat = Theme.Spacing.md
    @ViewBuilder var content: () -> Content

    init(padding: CGFloat = Theme.Spacing.md,
         @ViewBuilder content: @escaping () -> Content) {
        self.padding = padding
        self.content = content
    }

    var body: some View {
        content()
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liquidGlass(cornerRadius: Theme.Radius.card)
    }
}

// MARK: - 3) SandyNotice

/// تنبيه/خطأ دافئ بصوت ساندي: فقاعة ناعمة فيها أيقونة ساندي صغيرة + نص لطيف.
/// يحلّ محل سطر الخطأ الأحمر بكل مكان. النوع يغيّر اللون فقط (معلومة / تنبيه ودّي).
struct SandyNotice: View {
    enum Kind { case info, gentleWarning }

    let message: String
    var kind: Kind = .info

    init(_ message: String, kind: Kind = .info) {
        self.message = message
        self.kind = kind
    }

    var body: some View {
        HStack(alignment: .top, spacing: Theme.Spacing.sm) {
            SandyAvatar(size: 28, mood: kind == .gentleWarning ? .soft : .happy)
            Text(message)
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.primaryText)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(Theme.Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            let shape = RoundedRectangle(cornerRadius: Theme.Radius.bubble, style: .continuous)
            ZStack { shape.fill(.ultraThinMaterial); shape.fill(tint) }
        }
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.bubble, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.bubble, style: .continuous)
                .stroke(stroke, lineWidth: 1)
        )
    }

    private var tint: Color {
        switch kind {
        case .info:          return Theme.Colors.accent.opacity(0.08)
        case .gentleWarning: return Theme.Colors.warnSoft
        }
    }
    private var stroke: Color {
        switch kind {
        case .info:          return Theme.Colors.accent.opacity(0.20)
        case .gentleWarning: return Theme.Colors.warn.opacity(0.35)
        }
    }
}

// MARK: - 4) FloatingSandy

/// رفيق ساندي العائم (يقابل SandyCompanion بالويب): أفاتار صغير مثبّت بزاوية،
/// يقدر يطلّع فقاعة كلام قصيرة، وقابل للنقر. مصمّم ليُستعمل كـ overlay.
struct FloatingSandy: View {
    enum Corner { case bottomLeading, bottomTrailing }

    let message: String?
    var corner: Corner = .bottomTrailing
    var onTap: (() -> Void)? = nil

    @State private var bob = false
    @State private var showBubble = false

    init(message: String? = nil,
         corner: Corner = .bottomTrailing,
         onTap: (() -> Void)? = nil) {
        self.message = message
        self.corner = corner
        self.onTap = onTap
    }

    var body: some View {
        VStack(alignment: bubbleAlignment, spacing: Theme.Spacing.xs) {
            // فقاعة الكلام — فوق الأفاتار، تطلع بنعومة
            if let message, !message.isEmpty, showBubble {
                speechBubble(message)
                    .transition(.scale(scale: 0.7, anchor: .bottom).combined(with: .opacity))
            }

            // الأفاتار العائم — يطفو لأعلى/أسفل، قابل للنقر
            Button {
                if message != nil { withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) { showBubble.toggle() } }
                onTap?()
            } label: {
                // الشخصية = روبوت ساندي الكامل (SandyRobot) — يطفو ويغمز.
                SandyRobot(size: 56, happy: true, animated: true)
                    .shadow(color: Theme.Shadow.liftColor,
                            radius: Theme.Shadow.liftRadius, x: 0, y: Theme.Shadow.liftY)
                    .offset(y: bob ? -5 : 0)
            }
            .buttonStyle(.plain)
        }
        .padding(Theme.Spacing.lg)
        .onAppear {
            withAnimation(.easeInOut(duration: 2.6).repeatForever(autoreverses: true)) { bob = true }
            if message != nil {
                // تطلّع الفقاعة لحالها بعد لحظة (مثل ترحيب الويب)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    withAnimation(.spring(response: 0.45, dampingFraction: 0.75)) { showBubble = true }
                }
            }
        }
    }

    // محاذاة الفقاعة حسب الزاوية (RTL: leading/trailing تنقلب تلقائيًا)
    private var bubbleAlignment: HorizontalAlignment {
        corner == .bottomTrailing ? .trailing : .leading
    }

    @ViewBuilder
    private func speechBubble(_ text: String) -> some View {
        Text(text)
            .font(Theme.Typography.caption)
            .foregroundColor(Theme.Colors.primaryText)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, Theme.Spacing.sm)
            .padding(.horizontal, Theme.Spacing.md)
            .frame(maxWidth: 200, alignment: .leading)
            .liquidGlass(cornerRadius: Theme.Radius.bubble)
    }
}

// MARK: - SandyAvatar (وجه ساندي الروبوت — منقول من RobotFace.jsx بالويب)

/// أفاتار ساندي: روبوت ساندي نفسه (SandyRobot) — أزرق كهربائي بهالة وغمزة لطيفة،
/// نفس "وجه الروبوت" بالويب. `size` هو القطر؛ نلائم ارتفاع الروبوت داخله.
/// التوقيع العام `SandyAvatar(size:mood:)` ثابت — كل المستدعين يظلّون يشتغلون.
struct SandyAvatar: View {
    enum Mood { case happy, soft }

    var size: CGFloat = 40
    var mood: Mood = .happy

    var body: some View {
        // الروبوت أطول من عرضه (172/110)؛ نقيس عرضه عشان طوله يدخل ضمن `size`،
        // ثم نوسّطه في إطار مربّع `size×size` (يقابل دائرة الأفاتار القديمة).
        SandyRobot(size: size * (110.0 / 172.0),
                   blink: false,
                   happy: mood == .happy,
                   animated: true)
            .frame(width: size, height: size)
            .accessibilityLabel("ساندي")
    }
}
