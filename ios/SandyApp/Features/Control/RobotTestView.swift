import SwiftUI

/// فحص جسم الروبوت — قطعة قطعة.
///
/// الفكرة اللي بتخلي هاي الشاشة تستاهل الوجود: **المقياس**. كل باقي التحكّمات
/// موجودة أصلًا بصفحة التحكّم كبطاقات أجهزة عادية، وبتشتغل تمام. بس السؤال
/// «هل المايك الشمال شغّال؟» ما بينجاوب بزر — بينجاوب لما تكتم واحد، وتحكي،
/// وتشوف التاني لحاله بيتحرّك.
///
/// وهاد بالضبط بيفرز تلات أعطال ما بينفرزوا بأي طريقة تانية:
///   • المقياسين ما بيتحرّكوا  → المايكات ما بتسمع (تسليك أو تهيئة)
///   • التنين بيتحرّكوا وواحد مكتوم → المايكات معكوسة بالتوصيل
///   • واحد بيتحرّك دايمًا والتاني أبدًا → مايك ميت
///
/// القراءات بتيجي من نبضة اللوح كل خمس ثواني، فالمقياس بيتأخر شوي عن صوتك.
/// هاد مقصود: بديل النبضة مجرى بيانات دائم بيستهلك من نفس الوصلة اللي بتحمل
/// صوتها الحي.
struct RobotTestView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var store: DevicesStore
    let node: NodeItem

    /// أسماء الأجهزة اللي بيزرعها الخادم عند الاقتران (node_provision.PART_CATALOGUE).
    private enum Part {
        static let micLeft      = "sandy_mic_left"
        static let micRight     = "sandy_mic_right"
        static let micLeftGain  = "sandy_mic_left_gain"
        static let micRightGain = "sandy_mic_right_gain"
        static let volume       = "sandy_volume"
        static let speakerTest  = "sandy_speaker_test"
        static let noise        = "sandy_noise"
        static let face         = "sandy_face"
        static let head         = "sandy_head"
        static let gesture      = "sandy_gesture"
        static let buzzer       = "sandy_buzzer"
    }

    /// نقرا الوحدة من الستور بكل رسمة، مش من النسخة اللي انمررت عند الفتح —
    /// وإلا المقياس بيتجمّد ع أول قراءة والشاشة كلها بتفقد معناها.
    private var live: NodeItem { store.nodes.first(where: { $0.nodeId == node.nodeId }) ?? node }
    private var tele: NodeTelemetry? { live.telemetry }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.section) {
                if !live.online { offlineNotice }

                micSection
                speakerSection
                faceSection

                Color.clear.frame(height: Theme.Spacing.xl)
            }
            .padding(Theme.Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .navigationTitle(lang.s("robot.test.title"))
        // إعادة تحميل دورية: النبضة بتوصل كل خمس ثواني، فما في فايدة نسأل أسرع
        // من هيك — بنستهلك بطارية وبيانات بلا ولا قراءة جديدة. الحلقة بتتلغي
        // لحالها لما تطلع من الشاشة.
        .task {
            while !Task.isCancelled {
                await store.load(api: state.api)
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
        .refreshable { await store.load(api: state.api) }
    }

    // ── المايكات ─────────────────────────────────────────────────────────────

    private var micSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            SectionHeader(title: lang.s("robot.test.mics"))

            Text(lang.s("robot.test.mics.hint"))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)

            if tele?.hasMicReadings == true {
                micMeter(title: lang.s("robot.test.mic.left"),
                         level: tele?.micLeft ?? 0,
                         muted: tele?.micLeftMuted ?? false)
                micMeter(title: lang.s("robot.test.mic.right"),
                         level: tele?.micRight ?? 0,
                         muted: tele?.micRightMuted ?? false)
            } else {
                // ولا قراءة وصلت. غالبًا فيرموير أقدم من هاي الميزة — نقولها
                // بدل ما نرسم مقياسين ساكنين ع صفر ونخلي المستخدم يستنتج غلط.
                Text(lang.s("robot.test.mics.noreadings"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .padding(Theme.Spacing.md)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.Colors.surface)
                    .cornerRadius(Theme.Radius.card)
            }

            deviceRow(Part.micLeft)
            deviceRow(Part.micRight)
            deviceRow(Part.micLeftGain)
            deviceRow(Part.micRightGain)
            deviceRow(Part.noise)
        }
    }

    private func micMeter(title: String, level: Int, muted: Bool) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            HStack {
                Text(title).font(Theme.Typography.callout)
                if muted {
                    Image(systemName: "mic.slash.fill")
                        .font(.system(size: Theme.Icon.sm))
                        .foregroundColor(Theme.Colors.secondaryText)
                }
                Spacer(minLength: 0)
                Text("\(muted ? 0 : level)")
                    .font(Theme.Typography.caption.monospacedDigit())
                    .foregroundColor(Theme.Colors.secondaryText)
            }

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(Theme.Colors.surface)
                    Capsule()
                        .fill(muted ? Theme.Colors.secondaryText : Theme.Colors.accent)
                        .frame(width: geo.size.width * CGFloat(muted ? 0 : min(100, max(0, level))) / 100)
                }
            }
            .frame(height: 10)
            .animation(.easeOut(duration: 0.25), value: level)
        }
        // شريط بلا وصف = «صورة» بصوت القارئ، والمقياس هو كل معنى هاي الشاشة.
        // بنجمّع السطر كله بعنصر واحد بقيمة منطوقة، فالأعمى بيقدر يعمل نفس
        // الفحص: يكتم واحد، يحكي، ويسمع الرقم التاني بيتغيّر.
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(title)
        .accessibilityValue(muted ? lang.s("robot.test.mic.mutedValue")
                                  : "\(min(100, max(0, level)))٪")
    }

    // ── السماعة ──────────────────────────────────────────────────────────────

    private var speakerSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            SectionHeader(title: lang.s("robot.test.speaker"))
            Text(lang.s("robot.test.speaker.hint"))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
            deviceRow(Part.volume)
            deviceRow(Part.speakerTest)
        }
    }

    // ── الوش والرقبة ─────────────────────────────────────────────────────────

    private var faceSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            SectionHeader(title: lang.s("robot.test.body"))
            deviceRow(Part.face)
            // الرقبة: الخط بيوصلها لزاوية، والحركات بتخليها تعني إشي. التنين
            // فوق بعض قصدًا — «لف الراس ٦٠ درجة» و«أومي» تنين طلبين ع نفس
            // القطعة، وفصلهم بشاشة بيخلي واحد منهم يضيع.
            deviceRow(Part.head)
            deviceRow(Part.gesture)
            Text(lang.s("robot.test.gesture.hint"))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
            deviceRow(Part.buzzer)
        }
    }

    // ── مشترك ────────────────────────────────────────────────────────────────

    /// بطاقة الجهاز نفسها المستعملة بصفحة التحكّم — مش نسخة تانية منها.
    /// أي تحسين ع البطاقة بيوصل هون لحاله، وأي نوع تحكّم جديد بيشتغل بلا تعديل.
    /// الجزء اللي ما انزرع (لوح بلا سيرفو مثلًا) ببساطة ما بيتعرض.
    @ViewBuilder
    private func deviceRow(_ name: String) -> some View {
        if let device = store.devices.first(where: { $0.name == name }) {
            DeviceCard(device: device, store: store, onEdit: {})
        }
    }

    private var offlineNotice: some View {
        SandyNotice(lang.s("robot.test.offline"), kind: .gentleWarning)
    }
}
