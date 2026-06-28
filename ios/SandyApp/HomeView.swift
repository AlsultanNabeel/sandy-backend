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
    /// يفتح حساب المستخدم (ProfileView) كـ sheet — الحساب مش تبويب.
    @State private var showProfile = false
    /// يفتح ورقة إعادة ترتيب عناصر الرئيسية.
    @State private var showReorder = false

    var body: some View {
        ZStack {
            SandyBackground()
            scrollContent
        }
        .navigationTitle(lang.s("home.title"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            // أعلى-بداية: زر إعادة ترتيب عناصر الرئيسية.
            ToolbarItem(placement: .navigationBarLeading) {
                Button {
                    showReorder = true
                } label: {
                    Image(systemName: "arrow.up.arrow.down")
                }
                .accessibilityLabel(lang.s("home.reorder"))
            }
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
        .sheet(isPresented: $showReorder) {
            HomeReorderSheet(store: store)
        }
        .task { await store.loadIfNeeded(api: state.api) }
        .refreshable { await store.load(api: state.api) }
    }

    // MARK: - المحتوى القابل للتمرير

    private var scrollContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                greeting
                    .reveal(order: 0, key: store.revealKey)

                if store.loadFailed {
                    SandyNotice(lang.s("home.loadFailed"),
                                kind: .gentleWarning)
                        .reveal(order: 1, key: store.revealKey)
                }

                // العناصر بالترتيب الذي اختاره المستخدم (يُعاد ترتيبه من ورقة الترتيب).
                ForEach(Array(store.order.enumerated()), id: \.element.id) { idx, block in
                    blockView(block)
                        .reveal(order: idx + 1, key: store.revealKey)
                }

                // مساحة سفلية حتى ما تغطّي ساندي العائمة آخر بطاقة.
                Color.clear.frame(height: 96)
            }
            .padding(Theme.Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            // حركة لطيفة عند تبدّل اللقطة (الأرقام تتحرّك بنعومة).
            .animation(.spring(response: 0.5, dampingFraction: 0.85), value: store.revealKey)
        }
    }

    /// يبني العنصر المطلوب حسب نوعه — يخلّي ترتيب العرض مدفوعًا بـ `store.order`.
    @ViewBuilder
    private func blockView(_ block: HomeBlock) -> some View {
        switch block {
        case .proactive: proactiveCard
        case .glance:    glanceSection
        case .talk:      talkToSandyCard
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
                SandyAvatar(size: 44, mood: proactiveMood)
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
                                    .font(.system(size: 11, weight: .bold))
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

    // MARK: - بطاقة "احكي مع ساندي" البارزة

    private var talkToSandyCard: some View {
        Button {
            goToChat()
        } label: {
            HStack(alignment: .center, spacing: Theme.Spacing.md) {
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(lang.s("home.talk.title"))
                        .font(Theme.Typography.title)
                        .foregroundColor(Theme.Colors.onAccent)
                    Text(lang.s("home.talk.body"))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.onAccent.opacity(0.92))
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: Theme.Spacing.sm)
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(.system(size: 30, weight: .semibold))
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
            .shadow(color: Theme.Shadow.glowColor,
                    radius: Theme.Shadow.glowRadius, x: 0, y: 6)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(lang.s("home.talk.title"))
    }

    // MARK: - الأفعال

    /// يبدّل لتبويب ساندي (المحادثة سطحها الأساسي).
    private func goToChat() {
        goToTab(.sandy)
    }

    /// يبدّل لأي تبويب بحركة لطيفة.
    private func goToTab(_ tab: MainTab) {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
            selection = tab
        }
    }

    /// أوّل تحميل فقط (نتجنّب إعادة الجلب كل ما يرجع التبويب).

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
            return String(format: lang.s("home.proactive.reminder"), store.snapshot.nextReminderText, reminderWhenSuffix)
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
            return ProactiveAction(title: lang.s("home.proactive.action.tasks"), target: .tasks)
        }
        if !store.snapshot.nextReminderText.isEmpty {
            return ProactiveAction(title: lang.s("home.proactive.action.reminders"), target: .reminders)
        }
        if isWeekSpendingHigh {
            return ProactiveAction(title: lang.s("home.proactive.action.life"), target: .life)
        }
        return ProactiveAction(title: lang.s("home.proactive.action.chat"), target: .chat)
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

/// يحمل عنوان الزر + التبويب الهدف للفعل السياقي.
private struct ProactiveAction {
    let title: String
    let target: MainTab
}

// MARK: - بطاقة لمحة (مربّعة، قابلة للنقر)

/// بطاقة لمحة صغيرة: أيقونة ملوّنة + رقم بارز + وصف + تلميح اختياري.
/// النقر يبدّل للتبويب المناسب عبر closure.
private struct GlanceCard: View {
    let icon: String
    let tint: Color
    let value: String
    let label: String
    var hint: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            SandyCard {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    Image(systemName: icon)
                        .font(.system(size: 20, weight: .semibold))
                        .foregroundColor(tint)
                        .frame(width: 38, height: 38)
                        .background(tint.opacity(0.14))
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))

                    Text(value)
                        .font(Theme.Typography.title)
                        .foregroundColor(Theme.Colors.primaryText)
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)

                    Text(label)
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)

                    if let hint {
                        Text(hint)
                            .font(Theme.Typography.caption)
                            .foregroundColor(tint)
                            .lineLimit(1)
                            .minimumScaleFactor(0.7)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .buttonStyle(.plain)
    }
}

// MARK: - بطاقة لمحة عريضة (سطر تذكير)

/// بطاقة عريضة لأقرب تذكير: أيقونة + عنوان + وصف، قابلة للنقر.
private struct GlanceWideCard: View {
    let icon: String
    let tint: Color
    let title: String
    let subtitle: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            SandyCard {
                HStack(alignment: .center, spacing: Theme.Spacing.md) {
                    Image(systemName: icon)
                        .font(.system(size: 20, weight: .semibold))
                        .foregroundColor(tint)
                        .frame(width: 38, height: 38)
                        .background(tint.opacity(0.14))
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))

                    VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                        Text(title)
                            .font(Theme.Typography.headline)
                            .foregroundColor(Theme.Colors.primaryText)
                            .lineLimit(1)
                        Text(subtitle)
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.backward")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundColor(Theme.Colors.secondaryText.opacity(0.6))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .buttonStyle(.plain)
    }
}

// MARK: - دخول متدرّج (حركة حيوية)

/// مُعدِّل دخول لطيف: البطاقة تنزل قليلًا + تتلاشى للداخل، مع تأخير متدرّج
/// حسب ترتيبها — يعطي إحساس إن الشاشة "تتفتّح" حيّة. `key` يعيد التشغيل عند
/// كل تحميل/تحديث.
private struct RevealModifier: ViewModifier {
    let order: Int
    let key: Int
    @State private var shown = false

    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : 14)
            .onAppear { animateIn() }
            .onChange(of: key) { _ in
                // إعادة التشغيل عند تحديث اللقطة.
                shown = false
                animateIn()
            }
    }

    private func animateIn() {
        withAnimation(
            .spring(response: 0.5, dampingFraction: 0.85)
                .delay(Double(order) * 0.08)
        ) {
            shown = true
        }
    }
}

private extension View {
    /// يطبّق دخولًا متدرّجًا حسب الترتيب، يُعاد تشغيله عند تغيّر `key`.
    func reveal(order: Int, key: Int) -> some View {
        modifier(RevealModifier(order: order, key: key))
    }
}

// ─────────────────────────────────────────────────────────────────────────
// MARK: - الستور (مصدر الحقيقة للرئيسية)

/// يملك لقطة الرئيسية والجلب، مستقل عن دورة حياة الشاشة. الجلب بمهمة مملوكة
/// للستور فالسحب الملغى ما يلغيه. وحارس مهم: بعد أول تحميل ناجح، ما نكتب فوق
/// بياناتك الجيدة بلقطة فاضية/خطأ عابر — فلوحتك ما بتتصفّر ولا تطلّع "تعثرت".
// MARK: - ورقة إعادة الترتيب

/// ورقة بسيطة لإعادة ترتيب عناصر الرئيسية بالجر: قائمة بوضع تحرير دائم وأيدي جر.
/// كل نقلة تُحفظ فورًا، والرئيسية تعكسها مباشرة لأنها تقرأ نفس `store.order`.
private struct HomeReorderSheet: View {
    @ObservedObject var store: HomeStore
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                SandyBackground()
                List {
                    Section {
                        ForEach(store.order) { block in
                            HStack(spacing: Theme.Spacing.md) {
                                Image(systemName: block.icon)
                                    .foregroundColor(Theme.Colors.accent)
                                    .frame(width: 26)
                                Text(lang.s(block.titleKey))
                                    .font(Theme.Typography.body)
                                    .foregroundColor(Theme.Colors.primaryText)
                                Spacer(minLength: 0)
                            }
                            .listRowBackground(Color.clear)
                        }
                        .onMove { store.move(from: $0, to: $1) }
                    } header: {
                        Text(lang.s("home.reorderHint"))
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                            .textCase(nil)
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .environment(\.editMode, .constant(.active))
            }
            .navigationTitle(lang.s("home.reorderTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.s("common.done")) { dismiss() }
                }
            }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }
}

/// عناصر الرئيسية القابلة لإعادة الترتيب (التحية تبقى ترويسة ثابتة فوق). كل عنصر
/// له مفتاح عنوان وأيقونة لعرضه بورقة إعادة الترتيب.
enum HomeBlock: String, CaseIterable, Identifiable {
    case proactive, glance, talk
    var id: String { rawValue }
    var titleKey: String {
        switch self {
        case .proactive: return "home.block.proactive"
        case .glance:    return "home.block.glance"
        case .talk:      return "home.block.talk"
        }
    }
    var icon: String {
        switch self {
        case .proactive: return "sparkles"
        case .glance:    return "square.grid.2x2.fill"
        case .talk:      return "bubble.left.and.bubble.right.fill"
        }
    }
}

@MainActor
final class HomeStore: ObservableObject {
    @Published var snapshot = HomeSnapshot()
    @Published var loading = false
    @Published var loadFailed = false
    @Published var didAppear = false
    @Published var revealKey = 0
    /// ترتيب عناصر الرئيسية الذي اختاره المستخدم (محفوظ محليًا).
    @Published var order: [HomeBlock] = HomeBlock.allCases

    private var loadTask: Task<Void, Never>?
    private let orderKey = "sandy_home_order"

    init() { loadOrder() }

    /// يقرأ الترتيب المحفوظ ويُلحق أي عنصر جديد ما كان موجود (هجرة آمنة).
    func loadOrder() {
        let saved = UserDefaults.standard.stringArray(forKey: orderKey) ?? []
        var result = saved.compactMap { HomeBlock(rawValue: $0) }
        for b in HomeBlock.allCases where !result.contains(b) { result.append(b) }
        order = result
    }

    /// إعادة ترتيب عنصر (من ورقة الترتيب) ثم حفظ فوري.
    func move(from offsets: IndexSet, to destination: Int) {
        order.move(fromOffsets: offsets, toOffset: destination)
        UserDefaults.standard.set(order.map(\.rawValue), forKey: orderKey)
    }

    /// تحميل أوّل فقط (يتحكّم بدخول البطاقات المتدرّج).
    func loadIfNeeded(api: APIClient) async {
        guard !didAppear else { return }
        await load(api: api)
    }

    func load(api: APIClient) async {
        loadTask?.cancel()
        let task = Task { @MainActor in
            loading = true
            defer { loading = false }
            let snap = await api.getHomeSnapshot()
            let fullFail = snap.hadError
                && snap.openTasks == 0
                && snap.upcomingReminders.isEmpty
                && snap.weekExpenseTotal == 0
            // ما نمسح لوحة جيدة على خطأ/إلغاء عابر: نحدّث فقط لو نجح أو لسا ما عندنا بيانات.
            if !snap.hadError || !didAppear {
                snapshot = snap
                loadFailed = fullFail
            }
            didAppear = true
            revealKey += 1   // يعيد تشغيل دخول البطاقات المتدرّج.
        }
        loadTask = task
        await task.value
    }
}
