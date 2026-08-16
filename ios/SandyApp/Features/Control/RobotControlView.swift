import SwiftUI

/// صفحة الروبوت — جسم ساندي، منفصل عن أجهزة البيت.
///
/// ليش صفحة لحالها: صفحة التحكّم كانت بتحطّ رقبتها ووشها ومايكاتها بنفس القائمة
/// مع لمبة الصالة والمروحة. هدول إشيان مختلفان — الأول جسمها والتاني بيتك —
/// والخلط بينهن كان بيعمل قائمة طويلة ما إلها موضوع واحد، وكل مرّة بدك تلاقي
/// إشي لازم تقرا كل شي.
///
/// وليش أقسام مش قائمة وحدة: البطاقات المرصوفة تحت بعض كلها بنفس الوزن، فالعين
/// ما عندها وين تمسك. الأقسام بتعطي جواب سريع لسؤال «وين إعدادات الصوت؟» بدون
/// ما تقرا كل بطاقة بالطريق.
///
/// الترتيب مقصود: **اللي بتشوفه** (الوش والحركة والشاشة والإضاءة) قبل **اللي
/// بتسمعه** (المايكات والسماعة) قبل **الكاميرا**. اللي بتلمسه كل يوم فوق.
struct RobotControlView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var store: DevicesStore

    /// أسماء الأجهزة اللي بيزرعها الخادم (node_provision.PART_CATALOGUE).
    /// مكتوبة هون مرّة وحدة بدل ما تتناثر نصوص بكل الملف.
    private enum Part {
        static let face        = "sandy_face"
        static let gesture     = "sandy_gesture"
        static let head        = "sandy_head"
        static let screen      = "sandy_screen"
        static let led         = "sandy_led"
        static let buzzer      = "sandy_buzzer"
        static let micLeft     = "sandy_mic_left"
        static let micRight    = "sandy_mic_right"
        static let micLeftGain  = "sandy_mic_left_gain"
        static let micRightGain = "sandy_mic_right_gain"
        static let volume      = "sandy_volume"
        static let speakerTest = "sandy_speaker_test"
        static let noise       = "sandy_noise"

        static let camFlash     = "cam_flash"
        static let camFlashLvl  = "cam_flash_level"
        static let camFlashMode = "cam_flash_mode"
        static let camSnapshot  = "cam_snapshot"
        static let camStream    = "cam_stream"
        static let camFrameSize = "cam_framesize"
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.section) {
                if store.robotDevices.isEmpty {
                    emptyState
                } else {
                    section("robot.control.expression",
                            hint: "robot.control.expression.hint",
                            parts: [Part.face, Part.head, Part.gesture])

                    section("robot.control.screen",
                            hint: "robot.control.screen.hint",
                            parts: [Part.screen])

                    section("robot.control.light",
                            hint: "robot.control.light.hint",
                            parts: [Part.led])

                    section("robot.control.sound",
                            hint: "robot.control.sound.hint",
                            parts: [Part.volume, Part.speakerTest, Part.buzzer,
                                    Part.micLeft, Part.micRight,
                                    Part.micLeftGain, Part.micRightGain, Part.noise])

                    section("robot.control.camera",
                            hint: "robot.control.camera.hint",
                            parts: [Part.camSnapshot, Part.camStream, Part.camFlash,
                                    Part.camFlashLvl, Part.camFlashMode, Part.camFrameSize])

                    leftovers
                }

                Color.clear.frame(height: Theme.Spacing.xl)
            }
            .padding(Theme.Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .navigationTitle(lang.s("robot.control.title"))
        .refreshable { await store.load(api: state.api) }
    }

    // ── أقسام ────────────────────────────────────────────────────────────────

    /// قسم واحد. ما بيظهر إذا ولا وحدة من قطعه موجودة — لوح بلا كاميرا ما إله
    /// عنوان «كاميرا» فاضي تحته.
    @ViewBuilder
    private func section(_ titleKey: String, hint hintKey: String,
                         parts: [String]) -> some View {
        let present = parts.compactMap { name in
            store.robotDevices.first { $0.name == name }
        }
        if !present.isEmpty {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                SectionHeader(title: lang.s(titleKey))
                Text(lang.s(hintKey))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                ForEach(present) { device in
                    DeviceCard(device: device, store: store, onEdit: {})
                }
            }
        }
    }

    /// أي قطعة أعلنها اللوح وما إلها مكان بالأقسام فوق.
    ///
    /// موجود عشان فيرموير أحدث من التطبيق ما يخلّي قطعة تختفي بصمت. تظهر تحت
    /// عنوان عام — أقل جمالًا من مكانها الصح، وأصدق بكتير من غيابها.
    @ViewBuilder
    private var leftovers: some View {
        let placed: Set<String> = [
            Part.face, Part.head, Part.gesture, Part.screen, Part.led,
            Part.volume, Part.speakerTest, Part.buzzer,
            Part.micLeft, Part.micRight, Part.micLeftGain, Part.micRightGain,
            Part.noise,
            Part.camFlash, Part.camFlashLvl, Part.camFlashMode,
            Part.camSnapshot, Part.camStream, Part.camFrameSize,
        ]
        let rest = store.robotDevices.filter { !placed.contains($0.name) }
        if !rest.isEmpty {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                SectionHeader(title: lang.s("robot.control.other"))
                ForEach(rest) { device in
                    DeviceCard(device: device, store: store, onEdit: {})
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "figure.wave")
                .font(.system(size: Theme.Icon.xl))
                .foregroundColor(Theme.Colors.secondaryText)
            Text(lang.s("robot.control.empty.title"))
                .font(Theme.Typography.headline)
            Text(lang.s("robot.control.empty.hint"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Spacing.xxl)
    }
}
