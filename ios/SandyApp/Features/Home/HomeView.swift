import SwiftUI

/// التبويب الرئيسي — هاي مش مجرّد شاشة بداية، هاي ساندي نفسها.
///
/// الفكرة (رؤية المالك): ساندي فاهمة حياتك وواعية لكل شي، ومبادِرة — تطلّعلك
/// أشياء مفيدة ومتغيّرة وتقترح بذكاء. فالرئيسية لازم تحسّها حيّة وذكيّة، مو
/// أزرار جامدة.
///
/// كيف تتحقّق الحيوية والمبادرة هون:
///   • تحية دافئة تتبدّل حسب الوقت + اسمك المفضّل.
///   • "نظرة ساندي" — سطر مبادر يتأقلم مع حالتك الحقيقية (مهام متأخرة /
///     مهام اليوم / تذكير قادم / مصروف الأسبوع / تشجيع) — بصيغ متعدّدة.
///   • بطاقات لمحة سريعة (مهام اليوم / أقرب تذكير / مصروف الأسبوع) — كل وحدة
///     قابلة للنقر تنقلك لتبويبها.
///   • بطاقة بارزة "احكي مع ساندي" تشرح إنها تقدر تعمل أي شي من الشات،
///     والنقر عليها يبدّل لتبويب ساندي.
///   • رفيق ساندي العائم صار عالميًّا فوق كل التبويبات (SandyCompanionLayer في
///     MainTabView) فما عاد لكل شاشة رفيق خاص — نتجنّب ساندي مكرّرة.
///   • زر أفاتار أعلى-أمام يفتح حسابك (ProfileView كـ sheet) — الحساب مش تبويب.
///   • سحب للتحديث، دخول بطاقات متدرّج، وحالات تحميل/خطأ بصوت ساندي.
struct HomeView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    /// تبديل التبويب برمجيًّا — ممرَّر من MainTabView حتى نقدر نقفز لتبويب الشات.
    @Binding var selection: MainTab

    /// مصدر الحقيقة للرئيسية (يملك اللقطة + الجلب، مستقل عن الشاشة) — فالسحب
    /// الملغى ما يمسح لوحتك بأصفار.
    @StateObject private var store = HomeStore()
    /// تنبيه اليوم من ساندي (سؤال تعارف أو جملة مهام بشخصيتها) — المرحلة السابعة.
    @StateObject private var nudgeStore = DailyNudgeStore()
    /// يفتح حساب المستخدم (ProfileView) كـ sheet — الحساب مش تبويب.
    @State private var showProfile = false
    /// يفتح ورقة إعادة ترتيب عناصر الرئيسية.
    /// يفتح نافذة الإضافة السريعة (مهمة/تذكير/عادة/… بنقرة، بلا حكي).
    @State private var showQuickAdd = false

    var body: some View {
        // الخلفية موحّدة على مستوى MainTabView — لا نكرّرها بكل تبويب (طبقة مهدورة).
        scrollContent
        .navigationTitle(lang.s("home.title"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            // أعلى-نهاية: زر أفاتار ساندي يفتح حسابك (مش تبويب).
            ToolbarItem(placement: .navigationBarTrailing) {
                Button {
                    showProfile = true
                } label: {
                    SandyAvatar(size: 34, mood: .happy)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(lang.s("home.profile"))
            }
        }
        .sheet(isPresented: $showProfile) {
            // ProfileView يعتمد على EnvironmentObject، ولها NavigationStack خاص
            // حتى يظهر عنوانها وأزرار التعديل/الخروج صح داخل الـ sheet.
            NavigationStack { ProfileView() }
        }
        // نافذة الإضافة السريعة — تطفو بالنص (SandyPopup بخلفية شفافة).
        .fullScreenCover(isPresented: $showQuickAdd) {
            QuickAddSheet()
                .environmentObject(state)
                .environmentObject(lang)
        }
        .task { await store.loadIfNeeded(api: state.api) }
        .task { await nudgeStore.loadIfNeeded(api: state.api) }
        .refreshable { await store.load(api: state.api) }
    }

    // MARK: - المحتوى القابل للتمرير

    /// التحية ترويسة ثابتة، وتحتها لوح ودجات زي «يومي» و«حياتي».
    ///
    /// التحية مش ودجة: هي بتقول لك مين إنت وأي وقت الآن، وما إلها معنى مربّع
    /// جنب الطقس ولا معنى محذوفة. الباقي كله إلك — ترتيبه وحجمه وإذا بدك
    /// تشيله أصلًا.
    private var scrollContent: some View {
        VStack(spacing: 0) {
            greeting
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.top, Theme.Spacing.sm)

            CardBoard("home") {
                BoardCard("nudge", titleKey: "home.block.nudge",
                          icon: "sparkles", designHeight: 150) {
                    DailyNudgeCard(store: nudgeStore)
                }
                BoardCard("quickAdd", titleKey: "home.block.quickAdd",
                          icon: "plus.circle.fill", designHeight: 130) { quickAddCard }
                BoardCard("weather", titleKey: "home.block.weather",
                          icon: "cloud.sun.fill", designHeight: 200) {
                    NavigationLink { WeatherView() } label: { WeatherCard() }
                        .buttonStyle(.plain)
                }
                BoardCard("robotBody", titleKey: "home.block.robotBody",
                          icon: "figure.wave", designHeight: 120) {
                    NavigationLink { RobotHomeEntry() } label: { robotBodyCard }
                        .buttonStyle(.plain)
                }
                BoardCard("homeControl", titleKey: "home.block.homeControl",
                          icon: "house.fill", designHeight: 120) {
                    NavigationLink { ControlView() } label: { homeControlCard }
                        .buttonStyle(.plain)
                }
                BoardCard("proactive", titleKey: "home.block.proactive",
                          icon: "sparkles", designHeight: 150) { proactiveCard }
                BoardCard("glance", titleKey: "home.block.glance",
                          icon: "square.grid.2x2.fill", designHeight: 250) { glanceSection }
                if store.loadFailed {
                    BoardCard("loadFailed", titleKey: "home.block.loadFailed",
                              icon: "exclamationmark.triangle", designHeight: 90) {
                        SandyNotice(lang.s("home.loadFailed"), kind: .gentleWarning)
                    }
                }
            }
        }
    }

    // MARK: - التحية (حسب الوقت + الاسم)

    private var greeting: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            Text(greetingLine)
                .font(Theme.Typography.largeTitle)
                .foregroundColor(Theme.Colors.primaryText)
                .fixedSize(horizontal: false, vertical: true)
            Text(greetingSub)
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - نظرة ساندي (السطر المبادر)

    private var proactiveCard: some View {
        SandyCard {
            HStack(alignment: .top, spacing: Theme.Spacing.md) {
                Image(systemName: "sparkles")
                    .font(.system(size: Theme.Icon.lg, weight: .semibold))
                    .foregroundColor(Theme.Colors.accent)
                    .frame(width: 44, height: 44)
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(lang.s("home.proactive.title"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.accentDeep)
                    Text(proactiveLine)
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)

                    // زر فعل سياقي صغير — يقفز للتبويب الأنسب حسب حالتك.
                    if let action = proactiveAction {
                        Button {
                            goToTab(action.target)
                        } label: {
                            HStack(spacing: Theme.Spacing.xs) {
                                Text(action.title)
                                    .font(Theme.Typography.callout)
                                Image(systemName: "chevron.backward")
                                    .font(.system(size: Theme.Icon.sm, weight: .bold))
                            }
                            .foregroundColor(Theme.Colors.accent)
                        }
                        .buttonStyle(.plain)
                        .padding(.top, 2)
                    }
                }
                Spacer(minLength: 0)
            }
        }
    }

    // MARK: - لمحة سريعة (بطاقات قابلة للنقر)

    private var glanceSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            SectionHeader(title: lang.s("home.glance.section"))

            HStack(spacing: Theme.Spacing.md) {
                GlanceCard(
                    icon: "checklist",
                    tint: Theme.Colors.accent,
                    value: store.loading && store.snapshot.openTasks == 0 ? "…" : "\(store.snapshot.todayTasks)",
                    label: lang.s("home.glance.today.label"),
                    hint: store.snapshot.overdueTasks > 0
                        ? String(format: lang.s("home.glance.today.overdue"), "\(store.snapshot.overdueTasks)")
                        : nil
                ) { selection = .daily }

                GlanceCard(
                    icon: "creditcard",
                    tint: Theme.Colors.success,
                    value: spendingValue,
                    label: lang.s("home.glance.spending.label"),
                    hint: store.snapshot.todayExpenseTotal > 0
                        ? String(format: lang.s("home.glance.spending.today"), amount(store.snapshot.todayExpenseTotal))
                        : nil
                ) { selection = .life }
            }

            // أقرب تذكير — بطاقة عريضة (نص أطول).
            GlanceWideCard(
                icon: "bell.fill",
                tint: Theme.Colors.warn,
                title: reminderTitle,
                subtitle: reminderSubtitle
            ) { selection = .daily }
        }
    }

    // MARK: - بطاقة الإضافة السريعة (العنصر الأساسي بالرئيسية)

    /// بطاقة بارزة تفتح نافذة الإضافة السريعة — مهمة/تذكير/عادة/مصروف… بنقرة،
    /// بطريقة غير الحكي مع ساندي. هي العنصر المهيمن الواحد بالرئيسية.
    private var quickAddCard: some View {
        Button {
            showQuickAdd = true
        } label: {
            HStack(alignment: .center, spacing: Theme.Spacing.md) {
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(quickAddTitle)
                        .font(Theme.Typography.title)
                        .foregroundColor(Theme.Colors.onAccent)
                    Text(quickAddBody)
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.onAccent.opacity(0.92))
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: Theme.Spacing.sm)
                Image(systemName: "plus.circle.fill")
                    .font(.system(size: Theme.Icon.lg, weight: .semibold))
                    .foregroundColor(Theme.Colors.onAccent)
            }
            .padding(Theme.Spacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                LinearGradient(
                    colors: [Theme.Colors.accent, Theme.Colors.accentDeep],
                    startPoint: .topLeading, endPoint: .bottomTrailing)
            )
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
            .sandyGlow()
        }
        .liquidGlassPress()
        .accessibilityLabel(quickAddTitle)
    }

    // MARK: - بطاقة التحكّم بالبيت (مدخل لسطح التحكّم)

    /// بطاقة مدخل لشاشة التحكّم بالبيت — أيقونة + عنوان + وصف + chevron.
    /// تتبع نمط HubRowCard/GlanceWideCard حتى تنسجم مع باقي اللوحة.
    /// بطاقة جسم ساندي ع الرئيسية.
    private var robotBodyCard: some View {
        SandyCard {
            HStack(alignment: .center, spacing: Theme.Spacing.md) {
                Image(systemName: "figure.wave")
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(Theme.Colors.accent)
                    .frame(width: 38, height: 38)
                    .background(Theme.Colors.accent.opacity(0.14))
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control,
                                                style: .continuous))

                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(lang.s("robot.control.title"))
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Text(lang.s("robot.control.card.body"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.forward")
                    .font(.system(size: Theme.Icon.sm, weight: .semibold))
                    .foregroundColor(Theme.Colors.tertiaryText)
            }
        }
    }

    private var homeControlCard: some View {
        SandyCard {
            HStack(alignment: .center, spacing: Theme.Spacing.md) {
                Image(systemName: "house.fill")
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(Theme.Colors.accent)
                    .frame(width: 38, height: 38)
                    .background(Theme.Colors.accent.opacity(0.14))
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))

                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(lang.s("control.home.cardTitle"))
                        .font(Theme.Typography.headline)
                        .foregroundColor(Theme.Colors.primaryText)
                    Text(lang.s("control.home.cardBody"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.backward")
                    .font(.system(size: Theme.Icon.sm, weight: .bold))
                    .foregroundColor(Theme.Colors.tertiaryText)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    // عنوان/وصف الإضافة السريعة (نص inline ثنائي اللغة — تفادي مفتاح l10n جديد).
    private var quickAddTitle: String {
        lang.lang == .ar ? "إضافة سريعة" : "Quick Add"
    }
    private var quickAddBody: String {
        lang.lang == .ar
            ? "مهمة، تذكير، عادة، مصروف… بنقرة وحدة"
            : "Task, reminder, habit, expense… in one tap"
    }

    // MARK: - الأفعال

    /// يبدّل لأي تبويب بحركة لطيفة (تستعمله البطاقة المبادرة).
    private func goToTab(_ tab: MainTab) {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
            selection = tab
        }
    }

    // MARK: - أوّل تحميل فقط (نتجنّب إعادة الجلب كل ما يرجع التبويب).

    // MARK: - التحية (نصوص)

    private var preferredName: String {
        let p = state.onboarding.preferredName.trimmingCharacters(in: .whitespaces)
        if !p.isEmpty { return p }
        let n = state.onboarding.name.trimmingCharacters(in: .whitespaces)
        return n
    }

    private var greetingLine: String {
        let name = preferredName
        let suffix = name.isEmpty ? "" : String(format: lang.s("home.greeting.name.suffix"), name)
        let base: String
        switch timeBucket {
        case .morning:   base = lang.s("home.greeting.morning")
        case .afternoon: base = lang.s("home.greeting.afternoon")
        case .evening:   base = lang.s("home.greeting.evening")
        case .night:     base = lang.s("home.greeting.night")
        }
        return base + suffix
    }

    private var greetingSub: String {
        switch timeBucket {
        case .morning:   return lang.s("home.greeting.sub.morning")
        case .afternoon: return lang.s("home.greeting.sub.afternoon")
        case .evening:   return lang.s("home.greeting.sub.evening")
        case .night:     return lang.s("home.greeting.sub.night")
        }
    }

    private enum TimeBucket { case morning, afternoon, evening, night }

    private var timeBucket: TimeBucket {
        let h = Calendar.current.component(.hour, from: Date())
        switch h {
        case 5..<12:  return .morning
        case 12..<17: return .afternoon
        case 17..<22: return .evening
        default:      return .night
        }
    }

    // MARK: - نظرة ساندي (المنطق المبادر)

    /// السطر المبادر — يتأقلم مع حالتك الحقيقية، بصيغ متعدّدة حتى يحسّ حيّ.
    private var proactiveLine: String {
        if store.loading && !store.didAppear {
            return lang.s("home.proactive.loading")
        }
        if store.snapshot.overdueTasks > 0 {
            let n = store.snapshot.overdueTasks
            return String(format: lang.s("home.proactive.overdue"), "\(n)", pluralTasks(n))
        }
        if store.snapshot.todayTasks > 0 {
            let n = store.snapshot.todayTasks
            return String(format: lang.s("home.proactive.today"), "\(n)", pluralTasks(n))
        }
        if !store.snapshot.nextReminderText.isEmpty {
            return String(format: lang.s("home.proactive.reminder"),
                          store.snapshot.nextReminderText, reminderWhenSuffix)
        }
        if isWeekSpendingHigh {
            return String(format: lang.s("home.proactive.spendingHigh"), amount(store.snapshot.weekExpenseTotal))
        }
        if store.snapshot.openTasks > 0 {
            let n = store.snapshot.openTasks
            return String(format: lang.s("home.proactive.openTasks"), "\(n)", pluralTasks(n))
        }
        // ما في شي عالق — جملة مشجّعة متبدّلة (حسب اليوم حتى تحسّ حيّة).
        let cheers = lang.list("home.encourage")
        guard !cheers.isEmpty else { return "" }
        let idx = Calendar.current.component(.day, from: Date()) % cheers.count
        return cheers[idx]
    }

    /// مزاج أفاتار ساندي بالبطاقة المبادرة — ألطف لو في شي متأخّر/مصروف عالي.
    private var proactiveMood: SandyAvatar.Mood {
        (store.snapshot.overdueTasks > 0 || isWeekSpendingHigh) ? .soft : .happy
    }

    /// فعل سياقي صغير أسفل نظرة ساندي — يقفز للتبويب الأنسب.
    private var proactiveAction: ProactiveAction? {
        if store.loading && !store.didAppear { return nil }
        if store.snapshot.overdueTasks > 0 || store.snapshot.todayTasks > 0 || store.snapshot.openTasks > 0 {
            return ProactiveAction(title: lang.s("home.proactive.action.tasks"), target: .daily)
        }
        if !store.snapshot.nextReminderText.isEmpty {
            return ProactiveAction(title: lang.s("home.proactive.action.reminders"), target: .daily)
        }
        if isWeekSpendingHigh {
            return ProactiveAction(title: lang.s("home.proactive.action.life"), target: .life)
        }
        return ProactiveAction(title: lang.s("home.proactive.action.chat"), target: .sandy)
    }

    // MARK: - لمحة سريعة (نصوص)

    private var spendingValue: String {
        if store.loading && store.snapshot.weekExpenseTotal == 0 && !store.didAppear { return "…" }
        return amount(store.snapshot.weekExpenseTotal)
    }

    private var reminderTitle: String {
        store.snapshot.nextReminderText.isEmpty ? lang.s("home.reminder.none") : store.snapshot.nextReminderText
    }

    private var reminderSubtitle: String {
        if store.snapshot.nextReminderText.isEmpty {
            return lang.s("home.reminder.sub.add")
        }
        let when = Self.relativeTime(store.snapshot.nextReminderAt)
        return when.isEmpty
            ? lang.s("home.reminder.sub.fallback")
            : String(format: lang.s("home.reminder.sub.relative"), when)
    }

    /// لاحقة وقت التذكير للسطر المبادر (مثلاً " بعد ساعتين").
    private var reminderWhenSuffix: String {
        let when = Self.relativeTime(store.snapshot.nextReminderAt)
        return when.isEmpty ? "" : " \(when)"
    }

    // MARK: - أدوات مساعدة (أرقام/نصوص/وقت)

    /// مصروف الأسبوع "عالي"؟ — عتبة بسيطة ودّية (مش حُكم صارم).
    private var isWeekSpendingHigh: Bool {
        store.snapshot.weekExpenseTotal >= 500
    }

    /// تنسيق مبلغ بصيغة عربية بسيطة (بدون كسور لو رقم صحيح).
    private func amount(_ value: Double) -> String {
        let rounded = (value.rounded() == value)
        let num: String
        if rounded {
            num = String(Int(value))
        } else {
            num = String(format: "%.2f", value)
        }
        return "\(num) \(lang.s("home.currency"))"
    }

    /// جمع "مهمة" بشكل عربي بسيط حسب العدد.
    private func pluralTasks(_ n: Int) -> String {
        n == 1 ? lang.s("home.task.singular") : lang.s("home.task.plural")
    }

    /// وقت نسبي عربي لطيف من ISO (أو فاضي لو ما قدرنا نحلّله).
    private static func relativeTime(_ iso: String) -> String {
        guard !iso.isEmpty, let date = parseISO(iso) else { return "" }
        let fmt = RelativeDateTimeFormatter()
        fmt.locale = Locale(identifier: "ar")
        fmt.unitsStyle = .full
        return fmt.localizedString(for: date, relativeTo: Date())
    }

    /// مُحلِّل ISO متسامح (نفس منطق getHomeSnapshot: مع/بدون منطقة زمنية).
    private static func parseISO(_ s: String) -> Date? {
        if s.isEmpty { return nil }
        let full = ISO8601DateFormatter()
        full.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let d = full.date(from: s) { return d }
        if let d = plain.date(from: s) { return d }
        let noTZ = DateFormatter()
        noTZ.locale = Locale(identifier: "en_US_POSIX")
        noTZ.timeZone = TimeZone.current
        noTZ.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        if let d = noTZ.date(from: s) { return d }
        let dateOnly = DateFormatter()
        dateOnly.locale = Locale(identifier: "en_US_POSIX")
        dateOnly.timeZone = TimeZone.current
        dateOnly.dateFormat = "yyyy-MM-dd"
        return dateOnly.date(from: s)
    }
}

// MARK: - فعل سياقي صغير (نظرة ساندي)

// MARK: - بطاقة لمحة (مربّعة، قابلة للنقر)

// MARK: - بطاقة لمحة عريضة (سطر تذكير)

// MARK: - دخول متدرّج (حركة حيوية)

// ─────────────────────────────────────────────────────────────────────────
// MARK: - الستور (مصدر الحقيقة للرئيسية)

/// يملك لقطة الرئيسية والجلب، مستقل عن دورة حياة الشاشة. الجلب بمهمة مملوكة
/// للستور فالسحب الملغى ما يلغيه. وحارس مهم: بعد أول تحميل ناجح، ما نكتب فوق
/// بياناتك الجيدة بلقطة فاضية/خطأ عابر — فلوحتك ما بتتصفّر ولا تطلّع "تعثرت".
// MARK: - ورقة إعادة الترتيب
