import SwiftUI

// ─────────────────────────────────────────────────────────────────────────
//  SandyCompanionLayer — رفيق ساندي العائم الدائم (يقابل SandyCompanion بالويب).
//
//  الفكرة (مرآة frontend/src/companion/SandyCompanion.jsx): نسخة واحدة من ساندي
//  فوق كل التبويبات. تطفو بزاوية، تتنفّس ببوب عمودي خفيف، تطلّع فقاعة كلام
//  سياقية قصيرة، والأهم — تنتقل (تنزلق) لمكان مختلف على الشاشة كل ما يتبدّل
//  التبويب، تمامًا مثل رفيقة الويب اللي تتنقّل بين الصفحات.
//
//  الاستضافة: MainTabView يركّبها كـ overlay وحيد فوق الـ TabView، فتظهر نفس
//  ساندي على كل تبويب وتنزلق مع تغيّر `selection`. النقر عليها يقفز للشات.
//
//  iOS 16 فقط — لا topBarTrailing، لا @Observable، لا force-unwrap.
//  SandyRobot عرض خارجي بهالتوقيع بالضبط (نبرمج عليه):
//    struct SandyRobot: View {
//        var size: CGFloat = 80; var gaze: CGSize = .zero
//        var blink: Bool = false; var happy: Bool = false; var animated: Bool = true
//    }
// ─────────────────────────────────────────────────────────────────────────

/// رفيق ساندي العائم الدائم. يعرف التبويب الحالي حتى يضبط مكانه + رسالته +
/// مزاجه، وينزلق بين الزوايا عند تبدّل التبويب. النقر عليه ينفّذ `onTap`.
struct SandyCompanionLayer: View {
    @EnvironmentObject private var lang: LanguageManager

    /// التبويب الحالي — يقوده MainTabView عبر `selection`.
    let tab: MainTab
    /// فعل النقر (MainTabView يبدّل للشات).
    let onTap: () -> Void

    /// حجم الروبوت العائم (مقارب لرفيقة الويب الصغيرة).
    private let robotSize: CGFloat = 64

    // الحركة الحيّة: بوب عمودي، رمشة، ونظرة تمسح المكان لما تكون هادئة.
    @State private var bob = false
    @State private var blink = false
    @State private var gaze: CGSize = .zero
    @State private var showBubble = false

    init(tab: MainTab, onTap: @escaping () -> Void) {
        self.tab = tab
        self.onTap = onTap
    }

    var body: some View {
        // نلفّها بـ GeometryReader حتى نحسب زوايا الانتقال بالنسبة للشاشة كاملة،
        // فتنزلق ساندي من ركن لركن (مثل قفزات رفيقة الويب بين الصفحات).
        GeometryReader { geo in
            companion
                .position(anchorPoint(in: geo.size))
                // الانتقال: spring واضح حتى تشوفها "تطير" من مكان لمكان عند تبدّل التبويب.
                .animation(.spring(response: 0.6, dampingFraction: 0.72), value: tab)
        }
        // الطبقة كلها ما تمنع نقرات تحتها — فقط ساندي نفسها تستقبل النقر.
        .allowsHitTesting(true)
        .ignoresSafeArea(.keyboard)
        .onAppear { startIdleLoops() }
        .onChange(of: tab) { _ in announceTab() }
        .onAppear { announceTab() }
    }

    // MARK: - الرفيق (فقاعة + روبوت عائم)

    private var companion: some View {
        VStack(alignment: bubbleHAlignment, spacing: Theme.Spacing.xs) {
            // فقاعة الكلام — فوق الروبوت، تطلع بنعومة، قابلة للنقر.
            if showBubble, !message.isEmpty {
                speechBubble(message)
                    .transition(.scale(scale: 0.7, anchor: .bottom).combined(with: .opacity))
            }

            // الروبوت العائم — يطفو لأعلى/أسفل، قابل للنقر (يقفز للشات).
            Button(action: handleTap) {
                SandyRobot(
                    size: robotSize,
                    gaze: gaze,
                    blink: blink,
                    happy: isHappyTab,
                    animated: true
                )
                .shadow(color: Theme.Shadow.liftColor,
                        radius: Theme.Shadow.liftRadius, x: 0, y: Theme.Shadow.liftY)
                .offset(y: bob ? -5 : 0)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("ساندي")
        }
        // حجم ثابت للحاوية حتى يبقى مركز `.position` مستقرًّا أثناء الانتقال.
        .frame(width: companionWidth, alignment: bubbleFrameAlignment)
    }

    // MARK: - فقاعة الكلام (سطح ساندي + حدّ أكسنت + ذيل صغير)

    @ViewBuilder
    private func speechBubble(_ text: String) -> some View {
        Text(text)
            .font(Theme.Typography.caption)
            .foregroundColor(Theme.Colors.primaryText)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, Theme.Spacing.sm)
            .padding(.horizontal, Theme.Spacing.md)
            .frame(maxWidth: 190, alignment: .leading)
            .liquidGlass(cornerRadius: Theme.Radius.bubble)
            // الذيل الصغير — مربّع مدوّر بزاوية يشير لأسفل ناحية راس ساندي.
            .overlay(alignment: bubbleTailAlignment) {
                SandyBubbleTail()
                    .padding(.horizontal, Theme.Spacing.lg)
                    .offset(y: 5)
            }
            .contentShape(Rectangle())
            .onTapGesture { dismissBubble() }
            .accessibilityAddTraits(.isButton)
    }

    // MARK: - النقر

    private func handleTap() {
        // النقر على ساندي: لو الفقاعة مخفية رجّعها، وبكل الأحوال نفّذ فعل النقر (الشات).
        if !showBubble {
            withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) { showBubble = true }
        }
        onTap()
    }

    private func dismissBubble() {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) { showBubble = false }
    }

    // MARK: - الحلقات الحيّة (بوب + رمشة + نظرة تمسح)

    private func startIdleLoops() {
        // بوب عمودي لطيف يتكرّر للأبد (التنفّس).
        withAnimation(.easeInOut(duration: 2.6).repeatForever(autoreverses: true)) {
            bob = true
        }
        scheduleBlink()
        scheduleScan()
    }

    /// رمشة عشوائية كل بضع ثوانٍ (مثل blink loop بالويب).
    private func scheduleBlink() {
        let delay = Double.random(in: 3.0...6.0)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            blink = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.13) {
                blink = false
                scheduleBlink()
            }
        }
    }

    /// نظرة تمسح المكان لما تكون هادئة (تقابل SCAN بالويب).
    private func scheduleScan() {
        let delay = Double.random(in: 1.6...2.8)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            withAnimation(.easeInOut(duration: 0.5)) {
                gaze = CGSize(
                    width: CGFloat.random(in: -6...6),
                    height: CGFloat.random(in: -3...6)
                )
            }
            scheduleScan()
        }
    }

    /// عند تبدّل التبويب: تطلّع الفقاعة برسالة التبويب الجديدة، ثم تختفي لحالها.
    private func announceTab() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.55) {
            withAnimation(.spring(response: 0.45, dampingFraction: 0.75)) { showBubble = true }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 5.0) {
            withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) { showBubble = false }
        }
    }

    // MARK: - الانتقال (زوايا حسب التبويب)

    /// مركز ساندي داخل الشاشة حسب التبويب — تتنقّل بين الزوايا عند تبدّل التبويب.
    /// نخليها دائمًا بركن أسفل (مو بنص الشاشة) حتى ما تغطّي المحتوى، وننقلها
    /// يمين/يسار حسب التبويب فتحسّها "تطير" من مكان لمكان مثل رفيقة الويب.
    /// نرفعها زيادة على الشاشات اللي فيها زر عائم بالأسفل حتى تجلس فوقه مباشرة.
    private func anchorPoint(in size: CGSize) -> CGPoint {
        let half = companionWidth / 2
        // هوامش جانبية تترك مجال للفقاعة، وارتفاع كافٍ فوق شريط التبويبات.
        let leadingX = half + Theme.Spacing.md
        let trailingX = size.width - half - Theme.Spacing.md
        // ركن أسفل مريح فوق شريط التبويبات (ما يغطّي محتوى ولا يمنع نقراته).
        let bottomY = size.height - 150
        // أعلى شوي — تجلس فوق زر الإضافة العريض مباشرة (التذكيرات).
        let aboveAddButtonY = size.height - 200
        // فوق حقل الكتابة بالشات (مو بنص الشاشة ولا فوق الحقل).
        let aboveInputY = size.height - 172

        switch tab {
        case .home, .robot:
            // الرئيسية/الروبوت: ركن أسفل-يمين.
            return CGPoint(x: trailingX, y: bottomY)
        case .chat:
            // الشات: ركن أسفل-يمين فوق حقل الكتابة (مو بنص الشاشة).
            return CGPoint(x: trailingX, y: aboveInputY)
        case .search:
            // البحث: ركن أسفل-يسار (النتائج قائمة بالأعلى).
            return CGPoint(x: leadingX, y: bottomY)
        case .tasks:
            // المهام: ركن أسفل-يسار.
            return CGPoint(x: leadingX, y: bottomY)
        case .reminders:
            // التذكيرات: ركن أسفل-يمين، فوق زر الإضافة مباشرة.
            return CGPoint(x: trailingX, y: aboveAddButtonY)
        case .life:
            // حياتي: ركن أسفل-يسار.
            return CGPoint(x: leadingX, y: bottomY)
        case .focus:
            // الفوكس: ركن أسفل-يسار (المؤقّت بأعلى الشاشة).
            return CGPoint(x: leadingX, y: bottomY)
        }
    }

    /// هل ساندي مبسوطة بهالتبويب؟ (مزاج لكل تبويب).
    private var isHappyTab: Bool {
        switch tab {
        case .home, .chat, .life, .robot, .search: return true
        case .tasks, .reminders, .focus:           return false   // تركيز/تنظيم — مزاج أهدأ.
        }
    }

    // MARK: - الرسالة السياقية (قصيرة، لكل تبويب، عربي/إنجليزي)

    private var isAR: Bool { lang.lang == .ar }

    /// رسالة قصيرة سياقية لكل تبويب. fallback ثنائي اللغة inline (مسموح حسب المهمة
    /// لأن إضافة namespace جديد يتطلّب تعديل الـ registry خارج ملفاتنا الثلاثة).
    private var message: String {
        switch tab {
        case .home:
            return isAR ? "أهلين فيك! 👋" : "Hey there! 👋"
        case .chat:
            return isAR ? "احكيني، أنا سامعة." : "Talk to me, I'm listening."
        case .tasks:
            return isAR ? "نظّمهن سوا؟" : "Sort them out together?"
        case .reminders:
            return isAR ? "بذكّرك بكل شي." : "I'll remind you."
        case .life:
            return isAR ? "كيف ماشية حياتك؟" : "How's life going?"
        case .focus:
            return isAR ? "وقت التركيز؟ 🎯" : "Focus time? 🎯"
        case .robot:
            return isAR ? "أظبّطلك الغرفة؟ 🏠" : "Set the room for you? 🏠"
        case .search:
            return isAR ? "شو بدك أدوّرلك؟ 🔍" : "What should I look up? 🔍"
        }
    }

    // MARK: - هندسة المحاذاة (RTL-aware عبر leading/trailing)

    /// عرض ثابت لحاوية الرفيق — يثبّت مركز `.position` أثناء الانتقال ويترك
    /// مجالًا للفقاعة بدون ما تطلع برّا الشاشة.
    private var companionWidth: CGFloat { 200 }

    /// محاذاة الفقاعة أفقيًّا — جهة الزاوية اللي وقفت فيها ساندي.
    private var bubbleHAlignment: HorizontalAlignment {
        isLeadingTab ? .leading : .trailing
    }

    private var bubbleFrameAlignment: Alignment {
        isLeadingTab ? .leading : .trailing
    }

    private var bubbleTailAlignment: Alignment {
        isLeadingTab ? .bottomLeading : .bottomTrailing
    }

    /// تبويبات الجهة المبدئية (يسار بصري في RTL يصير يمين تلقائيًّا).
    private var isLeadingTab: Bool {
        switch tab {
        case .tasks, .life, .focus, .search:   return true
        case .home, .chat, .reminders, .robot: return false
        }
    }
}

// MARK: - ذيل الفقاعة (مربّع مدوّر بزاوية يشير لراس ساندي)

/// ذيل صغير أسفل فقاعة الكلام — مربّع بنفس سطح الفقاعة وحدّ الأكسنت، مدوّر 45°
/// حتى يبيّن كسهم يشير لأسفل ناحية ساندي (يقابل tail بفقاعة الويب).
private struct SandyBubbleTail: View {
    var body: some View {
        Rectangle()
            .fill(.ultraThinMaterial)
            .frame(width: 10, height: 10)
            .overlay(
                Rectangle()
                    .stroke(Theme.Colors.accent.opacity(0.30), lineWidth: 1)
            )
            .rotationEffect(.degrees(45))
    }
}
