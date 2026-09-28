import SwiftUI


// MARK: - 1) SandyButton

/// زر إجراء أساسي بنمطين: أساسي (مملوء) وثانوي (زجاجي)، مع حالة تحميل.
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
                    radius: style == .primary ? 6 : 0, x: 0, y: 3)
        }
        .buttonStyle(.plain)
        .disabled(isLoading)
        .opacity(isLoading ? 0.85 : 1)
    }

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
            // ثانوي = زجاج سائل.
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

/// حاوية البطاقة القياسية بدل تكرار الخلفيات يدويًا.
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

// MARK: - 2.5) SandyPopup

/// نافذة منبثقة بالنص؛ تُقدَّم عبر `.fullScreenCover` بخلفية شفافة وتقفل بـ `dismiss`.
struct SandyPopup<Content: View>: View {
    @Environment(\.dismiss) private var dismiss
    let title: String
    @ViewBuilder var content: () -> Content

    init(title: String, @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.content = content
    }

    var body: some View {
        ZStack {
            Color.black.opacity(0.55)
                .ignoresSafeArea()
                .onTapGesture { dismiss() }

            VStack(spacing: 0) {
                HStack {
                    Text(title)
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Spacer(minLength: Theme.Spacing.md)
                    Button { dismiss() } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.title3)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                    .buttonStyle(.plain)
                }
                .padding(Theme.Spacing.md)

                Divider().overlay(Theme.Colors.surface)

                // المحتوى قابل للتمرير حتى يبقى الارتفاع محدودًا.
                ScrollView {
                    content()
                        .padding(Theme.Spacing.md)
                }
                .frame(maxHeight: 440)
            }
            .frame(maxWidth: 460)
            .background(Theme.Colors.card)
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .stroke(Theme.Colors.surface, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.5), radius: 30, x: 0, y: 12)
            .padding(.horizontal, Theme.Spacing.lg)
        }
        .presentationBackground(.clear)
    }
}

// MARK: - 3) SandyNotice

/// تنبيه/خطأ دافئ بصوت ساندي بدل سطر الخطأ الأحمر.
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
            // زينة بحتة؛ بلا إخفائها قارئ الشاشة بيعلن «صورة» قبل كل رسالة.
            SandyAvatar(size: 28, mood: kind == .gentleWarning ? .soft : .happy)
                .accessibilityHidden(true)
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

/// رفيق ساندي العائم: أفاتار بزاوية مع فقاعة كلام اختيارية، يُستعمل كـ overlay.
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
            if let message, !message.isEmpty, showBubble {
                speechBubble(message)
                    .transition(.scale(scale: 0.7, anchor: .bottom).combined(with: .opacity))
            }

            Button {
                if message != nil {
                    withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) {
                        showBubble.toggle()
                    }
                }
                onTap?()
            } label: {
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
                // تطلّع الفقاعة لحالها بعد لحظة.
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    withAnimation(.spring(response: 0.45, dampingFraction: 0.75)) { showBubble = true }
                }
            }
        }
    }

    // RTL: leading/trailing تنقلب تلقائيًا.
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

// MARK: - SandyAvatar

/// روبوت ساندي داخل إطار مربّع؛ `size` هو القطر.
struct SandyAvatar: View {
    enum Mood { case happy, soft }

    var size: CGFloat = 40
    var mood: Mood = .happy

    var body: some View {
        // الروبوت أطول من عرضه (172/110): نقيس عرضه حتى طوله يدخل ضمن `size`.
        SandyRobot(size: size * (110.0 / 172.0),
                   blink: false,
                   happy: mood == .happy,
                   animated: true)
            .frame(width: size, height: size)
            .accessibilityLabel("ساندي")
    }
}

// MARK: - HubList

/// نخزّن مفاتيح l10n لا النص حتى تتبدّل اللغة بدون إعادة بناء المصفوفة.
struct HubRowSpec: Identifiable {
    let id = UUID()
    let icon: String
    let titleKey: String
    let subtitleKey: String
    let tint: Color
}

/// قائمة بطاقات NavigationLink لشاشات فرعية بدخول متدرّج.
struct HubList<Destination: View>: View {
    let rows: [HubRowSpec]
    @ViewBuilder let destination: (Int) -> Destination

    @State private var appeared = false

    var body: some View {
        ScrollView {
            VStack(spacing: Theme.Spacing.md) {
                ForEach(Array(rows.enumerated()), id: \.element.id) { index, spec in
                    NavigationLink {
                        destination(index)
                    } label: {
                        HubRowCard(spec: spec)
                    }
                    .buttonStyle(.plain)
                    .opacity(appeared ? 1 : 0)
                    .offset(y: appeared ? 0 : 16)
                    .animation(.spring(response: 0.5, dampingFraction: 0.8)
                                .delay(Double(index) * 0.08),
                               value: appeared)
                }
            }
            .padding(Theme.Spacing.md)
        }
        .onAppear { appeared = true }
    }
}

struct HubRowCard: View {
    @EnvironmentObject private var lang: LanguageManager
    let spec: HubRowSpec

    var body: some View {
        HStack(spacing: Theme.Spacing.md) {
            ZStack {
                Circle()
                    .fill(spec.tint.opacity(0.14))
                    .frame(width: 44, height: 44)
                Image(systemName: spec.icon)
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(spec.tint)
            }
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(lang.s(spec.titleKey))
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                Text(lang.s(spec.subtitleKey))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.tertiaryText)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.forward")
                .font(.system(size: Theme.Icon.sm, weight: .semibold))
                .foregroundColor(Theme.Colors.tertiaryText)
        }
        .sandyCard()
    }
}
