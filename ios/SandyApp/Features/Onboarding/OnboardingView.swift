import SwiftUI
import UIKit
import AVFAudio
import UserNotifications

/// أول تشغيل: أربع صفحات قصيرة — تعرّف على ساندي، شو بتعمل، اسمك واهتماماتك،
/// والأذونات وقت الحاجة. العقد مع باقي التطبيق ما تغيّر: نحفظ الاسم والاهتمامات
/// عبر `saveOnboarding`، ثم `onboardingDoneCached = true` و`stage = .chat`.
///
/// التنقّل بأزرار (مش سحب) عن قصد: اتجاه اللغة مفروض من البيئة، والسحب داخل
/// الـ TabView بنمط الصفحات بيلخبط اتجاهه لما يختلف عن لغة الجهاز.
struct OnboardingView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var page = 0
    @State private var forward = true
    @State private var preferredName = ""
    @State private var interests: [String] = []
    @State private var customInterest = ""
    @State private var error = ""
    @State private var saving = false
    @State private var notifStatus: PermissionState = .idle
    @State private var micStatus: PermissionState = .idle
    @FocusState private var focused: Field?

    private enum Field { case name, custom }
    enum PermissionState { case idle, granted, denied, skipped }

    private let pageCount = 4
    private let namePage = 2

    private var trimmedName: String {
        preferredName.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    private var canAdvance: Bool { page != namePage || !trimmedName.isEmpty }
    private var isLastPage: Bool { page == pageCount - 1 }

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                topBar
                pageContent
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                bottomBar
            }
            .frame(maxWidth: 520)
            .frame(maxWidth: .infinity)
        }
        .dynamicTypeSize(...DynamicTypeSize.accessibility3)
        .task {
            await refreshNotifStatus()
            refreshMicStatus()
        }
        // رجعنا من نافذة الإذن أو من الإعدادات → نحدّث حالة البطاقات.
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            Task { await refreshNotifStatus() }
            refreshMicStatus()
        }
    }

    // MARK: - الشريط العلوي

    private var topBar: some View {
        HStack(spacing: Theme.Spacing.sm) {
            Group {
                if page > 0 {
                    Button(action: goBack) {
                        Image(systemName: "chevron.backward")
                            .font(.system(size: Theme.Icon.md, weight: .semibold))
                            .foregroundColor(Theme.Colors.primaryText)
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(LiquidGlassButtonStyle())
                    .accessibilityLabel(lang.s("onboarding.back"))
                    .transition(.opacity)
                } else {
                    Color.clear.frame(width: 44, height: 44)
                }
            }
            .frame(minWidth: 72, alignment: .leading)

            Spacer(minLength: 0)
            LanguageToggle().frame(width: 110)
            Spacer(minLength: 0)

            Group {
                if page < namePage {
                    Button(action: skipToName) {
                        Text(lang.s("onboarding.skip"))
                            .font(.callout.weight(.medium))
                            .foregroundColor(Theme.Colors.secondaryText)
                            .frame(minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .transition(.opacity)
                } else {
                    Color.clear.frame(width: 44, height: 44)
                }
            }
            .frame(minWidth: 72, alignment: .trailing)
        }
        .padding(.horizontal, Theme.Spacing.lg)
        .padding(.top, Theme.Spacing.sm)
        .animation(.easeInOut(duration: 0.2), value: page)
    }

    // MARK: - الصفحات

    private var pageTransition: AnyTransition {
        .asymmetric(
            insertion: .move(edge: forward ? .trailing : .leading).combined(with: .opacity),
            removal: .opacity)
    }

    private var pageContent: some View {
        ZStack {
            switch page {
            case 0: welcomePage.transition(pageTransition)
            case 1: featuresPage.transition(pageTransition)
            case 2: aboutPage.transition(pageTransition)
            default: permissionsPage.transition(pageTransition)
            }
        }
        .clipped()
    }

    /// غلاف موحّد: كل صفحة بتتمرّر لو ما وسعتها الشاشة (شاشات صغيرة/خط كبير).
    private func pageScroll<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        ScrollView {
            VStack(spacing: Theme.Spacing.xl) {
                content()
            }
            .padding(.horizontal, Theme.Spacing.lg)
            .padding(.vertical, Theme.Spacing.lg)
            .frame(maxWidth: .infinity)
        }
        .scrollBounceBehavior(.basedOnSize)
        .scrollDismissesKeyboard(.interactively)
    }

    private func header(_ titleKey: String, _ bodyKey: String?) -> some View {
        VStack(spacing: Theme.Spacing.sm) {
            Text(lang.s(titleKey))
                .font(.system(.title, design: .rounded, weight: .bold))
                .foregroundColor(Theme.Colors.primaryText)
                .multilineTextAlignment(.center)
            if let bodyKey {
                Text(lang.s(bodyKey))
                    .font(.body)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity)
    }

    // ١ — تعرّف على ساندي
    private var welcomePage: some View {
        pageScroll {
            Spacer(minLength: Theme.Spacing.lg)
            ZStack {
                Circle()
                    .fill(RadialGradient(
                        colors: [Theme.Colors.accent.opacity(0.24), .clear],
                        center: .center, startRadius: 0, endRadius: 130))
                    .frame(width: 260, height: 260)
                TimelineView(.animation(minimumInterval: nil, paused: reduceMotion)) { ctx in
                    let t = ctx.date.timeIntervalSinceReferenceDate
                    SandyRobot(size: 120, happy: true)
                        .offset(y: reduceMotion ? 0 : CGFloat(sin(t * 1.4)) * 6)
                }
            }
            .accessibilityHidden(true)

            VStack(spacing: Theme.Spacing.md) {
                Text(lang.s("onboarding.welcomeTitle"))
                    .font(.system(.largeTitle, design: .rounded, weight: .bold))
                    .foregroundColor(Theme.Colors.primaryText)
                    .multilineTextAlignment(.center)
                Text(lang.s("onboarding.welcomeBody"))
                    .font(.title3)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .accessibilityElement(children: .combine)
        }
    }

    // ٢ — شو بتعمل
    private var featuresPage: some View {
        pageScroll {
            SandyAvatar(size: 64, mood: .happy)
                .accessibilityHidden(true)
            header("onboarding.featuresTitle", nil)
            VStack(spacing: Theme.Spacing.md) {
                featureRow(icon: "waveform.and.mic",
                           title: lang.s("onboarding.featChatTitle"),
                           body: lang.s("onboarding.featChatBody"))
                featureRow(icon: "checklist",
                           title: lang.s("onboarding.featTasksTitle"),
                           body: lang.s("onboarding.featTasksBody"))
                featureRow(icon: "house.fill",
                           title: lang.s("onboarding.featRobotTitle"),
                           body: lang.s("onboarding.featRobotBody"))
            }
        }
    }

    private func featureRow(icon: String, title: String, body: String) -> some View {
        HStack(alignment: .top, spacing: Theme.Spacing.md) {
            iconBadge(icon)
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(title)
                    .font(.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                Text(body)
                    .font(.subheadline)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .sandyCard()
        .accessibilityElement(children: .combine)
    }

    private func iconBadge(_ icon: String) -> some View {
        Image(systemName: icon)
            .font(.system(size: Theme.Icon.md, weight: .semibold))
            .foregroundColor(Theme.Colors.accent)
            .frame(width: 42, height: 42)
            .background(
                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                    .fill(Theme.Colors.accent.opacity(0.12)))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                    .stroke(Theme.Colors.border, lineWidth: 1))
            .accessibilityHidden(true)
    }

    // ٣ — اسمك واهتماماتك
    private var suggestions: [String] { lang.list("onboarding.suggestions") }

    /// الاقتراحات + أي اهتمام مختار مش منها (مخصّص، أو من اللغة التانية).
    private var chipItems: [String] {
        suggestions + interests.filter { !suggestions.contains($0) }
    }

    private var aboutPage: some View {
        pageScroll {
            SandyAvatar(size: 64, mood: .happy)
                .accessibilityHidden(true)
            header("onboarding.title", nil)

            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                Text(lang.s("onboarding.nameLabel"))
                    .font(.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                TextField(lang.s("onboarding.namePlaceholder"), text: $preferredName)
                    .textFieldStyle(.plain)
                    .textContentType(.givenName)
                    .submitLabel(.next)
                    .focused($focused, equals: .name)
                    .onSubmit { focused = .custom }
                    .modifier(OnboardingField())
            }

            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                Text(lang.s("onboarding.interestsLabel"))
                    .font(.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                Text(lang.s("onboarding.interestsHint"))
                    .font(.subheadline)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)

                OnboardingChipLayout(spacing: Theme.Spacing.sm) {
                    ForEach(chipItems, id: \.self) { item in
                        chip(item)
                    }
                }
                .padding(.vertical, Theme.Spacing.xs)
                .animation(.spring(response: 0.3, dampingFraction: 0.8), value: interests)

                HStack(spacing: Theme.Spacing.sm) {
                    TextField(lang.s("onboarding.interestsPlaceholder"), text: $customInterest)
                        .textFieldStyle(.plain)
                        .submitLabel(.done)
                        .focused($focused, equals: .custom)
                        .onSubmit(addCustom)
                        .modifier(OnboardingField())
                    Button(action: addCustom) {
                        Image(systemName: "plus")
                            .font(.system(size: Theme.Icon.md, weight: .bold))
                            .foregroundColor(Theme.Colors.onAccent)
                            .frame(width: 48, height: 48)
                            .background(
                                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                                    .fill(Theme.Colors.accent))
                    }
                    .buttonStyle(LiquidGlassButtonStyle())
                    .disabled(customInterest.trimmingCharacters(in: .whitespaces).isEmpty)
                    .opacity(customInterest.trimmingCharacters(in: .whitespaces).isEmpty ? 0.45 : 1)
                    .accessibilityLabel(lang.s("onboarding.add"))
                }
            }
        }
    }

    private func chip(_ item: String) -> some View {
        let on = interests.contains(item)
        return Button { toggle(item) } label: {
            HStack(spacing: Theme.Spacing.xs) {
                if on {
                    Image(systemName: "checkmark")
                        .font(.caption.weight(.bold))
                }
                Text(item)
                    .font(.subheadline.weight(.medium))
            }
            .foregroundColor(on ? Theme.Colors.onAccent : Theme.Colors.primaryText)
            .padding(.vertical, Theme.Spacing.sm)
            .padding(.horizontal, Theme.Spacing.md)
            .background {
                if on {
                    Capsule().fill(LinearGradient(
                        colors: [Theme.Colors.accent, Theme.Colors.accentDeep],
                        startPoint: .topLeading, endPoint: .bottomTrailing))
                } else {
                    Capsule().fill(Theme.Colors.surface)
                }
            }
            .overlay(Capsule().stroke(on ? Color.clear : Theme.Colors.border, lineWidth: 1))
        }
        .buttonStyle(LiquidGlassButtonStyle())
        .accessibilityAddTraits(on ? .isSelected : [])
    }

    private func toggle(_ item: String) {
        Haptics.play(.selection)
        if let i = interests.firstIndex(of: item) {
            interests.remove(at: i)
        } else {
            interests.append(item)
        }
    }

    /// يضيف اهتمامًا مخصّصًا (يقبل عدّة مفصولة بفاصلة عربية أو إنجليزية).
    private func addCustom() {
        let parts = customInterest
            .split(whereSeparator: { $0 == "," || $0 == "،" })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        guard !parts.isEmpty else { return }
        for p in parts where !interests.contains(p) { interests.append(p) }
        customInterest = ""
        Haptics.play(.selection)
    }

    // ٤ — الأذونات
    private var permissionsPage: some View {
        pageScroll {
            SandyAvatar(size: 64, mood: .happy)
                .accessibilityHidden(true)
            header("onboarding.permsTitle", "onboarding.permsBody")
            VStack(spacing: Theme.Spacing.md) {
                permissionCard(icon: "bell.badge.fill",
                               title: lang.s("onboarding.notifTitle"),
                               body: lang.s("onboarding.notifBody"),
                               status: notifStatus,
                               allow: allowNotifications,
                               notNow: { notifStatus = .skipped; Haptics.play(.selection) })
                permissionCard(icon: "mic.fill",
                               title: lang.s("onboarding.micTitle"),
                               body: lang.s("onboarding.micBody"),
                               status: micStatus,
                               allow: allowMic,
                               notNow: { micStatus = .skipped; Haptics.play(.selection) })
            }
            if !error.isEmpty {
                SandyNotice(error, kind: .gentleWarning)
            }
        }
    }

    private func permissionCard(icon: String, title: String, body: String,
                                status: PermissionState,
                                allow: @escaping () -> Void,
                                notNow: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            HStack(alignment: .top, spacing: Theme.Spacing.md) {
                iconBadge(icon)
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(title)
                        .font(.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Text(body)
                        .font(.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .accessibilityElement(children: .combine)

            switch status {
            case .idle:
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: Theme.Spacing.sm) {
                        SandyButton(title: lang.s("onboarding.allow"), fillWidth: true, action: allow)
                        SandyButton(title: lang.s("onboarding.notNow"), style: .secondary,
                                    fillWidth: true, action: notNow)
                    }
                    VStack(spacing: Theme.Spacing.sm) {
                        SandyButton(title: lang.s("onboarding.allow"), fillWidth: true, action: allow)
                        SandyButton(title: lang.s("onboarding.notNow"), style: .secondary,
                                    fillWidth: true, action: notNow)
                    }
                }
            case .granted:
                statusLabel("checkmark.circle.fill", lang.s("onboarding.granted"), Theme.Colors.success)
            case .denied:
                HStack {
                    statusLabel("xmark.circle", lang.s("onboarding.denied"), Theme.Colors.warn)
                    Spacer(minLength: Theme.Spacing.sm)
                    textAction(lang.s("onboarding.openSettings"), action: openSettings)
                }
            case .skipped:
                HStack {
                    statusLabel("clock", lang.s("onboarding.later"), Theme.Colors.tertiaryText)
                    Spacer(minLength: Theme.Spacing.sm)
                    textAction(lang.s("onboarding.allow"), action: allow)
                }
            }
        }
        .sandyCard(status == .granted ? .info : .secondary)
        .animation(.easeInOut(duration: 0.2), value: status)
    }

    private func statusLabel(_ icon: String, _ text: String, _ color: Color) -> some View {
        Label(text, systemImage: icon)
            .font(.callout.weight(.semibold))
            .foregroundColor(color)
    }

    private func textAction(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.callout.weight(.semibold))
                .foregroundColor(Theme.Colors.accent)
                .frame(minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: - الشريط السفلي

    private var bottomBar: some View {
        VStack(spacing: Theme.Spacing.md) {
            pageDots
            SandyButton(title: lang.s(isLastPage ? "onboarding.save" : "onboarding.next"),
                        systemImage: isLastPage ? "sparkles" : nil,
                        isLoading: saving,
                        fillWidth: true,
                        action: goNext)
                .disabled(!canAdvance)
                .opacity(canAdvance ? 1 : 0.5)
        }
        .padding(.horizontal, Theme.Spacing.lg)
        .padding(.top, Theme.Spacing.sm)
        .padding(.bottom, Theme.Spacing.md)
    }

    private var pageDots: some View {
        HStack(spacing: 6) {
            ForEach(0..<pageCount, id: \.self) { i in
                Capsule()
                    .fill(i == page ? Theme.Colors.accent : Theme.Colors.primaryText.opacity(0.18))
                    .frame(width: i == page ? 22 : 7, height: 7)
            }
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: page)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(lang.s("onboarding.progress"))
        .accessibilityValue("\(page + 1) / \(pageCount)")
    }

    // MARK: - التنقّل

    private func goNext() {
        guard canAdvance, !saving else { return }
        if isLastPage { save(); return }
        move(to: page + 1)
    }

    private func goBack() {
        guard page > 0 else { return }
        move(to: page - 1)
    }

    private func skipToName() { move(to: namePage) }

    private func move(to target: Int) {
        focused = nil
        forward = target > page
        Haptics.play(.selection)
        withAnimation(reduceMotion ? .easeInOut(duration: 0.2)
                                   : .spring(response: 0.45, dampingFraction: 0.88)) {
            page = target
        }
    }

    // MARK: - الأذونات (وقت الحاجة فقط)

    private func allowNotifications() {
        Haptics.play(.selection)
        NotificationManager.shared.requestAuthorization()
        // لو الإذن محسوم من قبل ما بتطلع نافذة، فنحدّث الحالة بعد لحظة؛ ولو
        // طلعت، بنحدّث لما يرجع التطبيق نشط (onChange scenePhase).
        Task {
            try? await Task.sleep(for: .milliseconds(800))
            await refreshNotifStatus()
        }
    }

    private func refreshNotifStatus() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            notifStatus = .granted
        case .denied:
            notifStatus = .denied
        default:
            if notifStatus != .skipped { notifStatus = .idle }
        }
    }

    private func allowMic() {
        Haptics.play(.selection)
        Task {
            let granted = await AVAudioApplication.requestRecordPermission()
            micStatus = granted ? .granted : .denied
        }
    }

    private func refreshMicStatus() {
        switch AVAudioApplication.shared.recordPermission {
        case .granted: micStatus = .granted
        case .denied:  micStatus = .denied
        default:       if micStatus != .skipped { micStatus = .idle }
        }
    }

    private func openSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }

    // MARK: - الحفظ (نفس العقد)

    private func save() {
        saving = true; error = ""
        let name = trimmedName
        let chosen = interests
        Task {
            do {
                try await state.api.saveOnboarding(preferredName: name, interests: chosen)
                Haptics.play(.success)
                state.onboardingDoneCached = true
                state.stage = .chat
            } catch {
                Haptics.play(.failure)
                self.error = error.localizedDescription
            }
            saving = false
        }
    }
}

// MARK: - حقل إدخال

/// نفس مظهر حقول شاشة الدخول: سطح داكن + حدّ كهربائي خفيف.
private struct OnboardingField: ViewModifier {
    func body(content: Content) -> some View {
        content
            .font(.body)
            .foregroundColor(Theme.Colors.primaryText)
            .tint(Theme.Colors.accent)
            .padding(.vertical, Theme.Spacing.md)
            .padding(.horizontal, Theme.Spacing.md)
            .background(Theme.Colors.surface)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                    .stroke(Theme.Colors.border, lineWidth: 1))
    }
}

// MARK: - تخطيط الشرائح (يلفّ للسطر التالي)

/// تخطيط بسيط يرصّ الشرائح بسطور ويلفّ عند امتلاء العرض. SwiftUI بيعكس
/// التخطيطات المخصّصة تلقائيًّا بالعربي، فالترتيب بيبدأ من اليمين.
private struct OnboardingChipLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, widest: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(ProposedViewSize(width: maxWidth, height: nil))
            if x > 0 && x + size.width > maxWidth {
                y += rowHeight + spacing
                x = 0
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            widest = max(widest, x - spacing)
        }
        let width = proposal.width ?? widest
        return CGSize(width: width.isFinite ? width : widest, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize,
                       subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, rowHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(ProposedViewSize(width: bounds.width, height: nil))
            if x > bounds.minX && x + size.width > bounds.maxX {
                y += rowHeight + spacing
                x = bounds.minX
                rowHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}
