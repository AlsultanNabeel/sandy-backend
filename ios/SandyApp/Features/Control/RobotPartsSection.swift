import PhotosUI
import SwiftUI

/// قطع ساندي اللي مش بالأزرار السريعة فوق — الرقبة والشاشة والصوت والكاميرا، وأي
/// قطعة تانية أعلنها اللوح. على شاشة الروبوت نفسها، تحت حالتها: كل إشي بمكان واحد.
///
/// المزاج والحركات والنغمات والإضاءة مش هون: إلهن أزرار سريعة فوق (`RobotLiveSection`)،
/// وبطاقة تانية لنفس القطعة بتكرّر نفس الأمر.
struct RobotPartsSection: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var store: DevicesStore

    @State private var pickedImage: PhotosPickerItem?
    @State private var sendingImage = false
    @State private var imageNotice = ""

    /// أسماء الأجهزة اللي بيزرعها الخادم (node_provision.PART_CATALOGUE).
    /// مكتوبة هون مرّة وحدة بدل ما تتناثر نصوص بكل الملف.
    private enum Part {
        static let head        = "sandy_head"
        static let screen      = "sandy_screen"
        static let micLeft     = "sandy_mic_left"
        static let micRight    = "sandy_mic_right"
        static let micLeftGain  = "sandy_mic_left_gain"
        static let micRightGain = "sandy_mic_right_gain"
        static let volume      = "sandy_volume"
        static let speakerTest = "sandy_speaker_test"

        static let camFlash     = "cam_flash"
        static let camFlashLvl  = "cam_flash_level"
        static let camFlashMode = "cam_flash_mode"
        static let camSnapshot  = "cam_snapshot"
        static let camStream    = "cam_stream"
        static let camFrameSize = "cam_framesize"
        // الوضوح جنب الدقّة بالقصد: الاتنين بيتلخبطوا ببعض، وبعدهن عن بعض
        // بيخلّي المالك يكبّر الدقّة ويستغرب إنّ الصورة ضلّت مغبّشة.
        static let camQuality   = "cam_quality"

        /// The parts the quick buttons above already drive.
        static let quick: Set<String> = [SandyMood.Device.face, SandyMood.Device.gesture,
                                         SandyMood.Device.buzzer, SandyMood.Device.led]
    }

    /// The order: what you see (neck, screen), what you hear (sound), then the camera.
    var body: some View {
        VStack(spacing: Theme.Spacing.md) {
            section("robot.control.neck", icon: "arrow.left.and.right.circle",
                    hint: "robot.control.neck.hint", parts: [Part.head])
            screenSection
            section("robot.control.sound", icon: "speaker.wave.2.fill",
                    hint: "robot.control.sound.hint",
                    parts: [Part.volume, Part.speakerTest,
                            Part.micLeft, Part.micRight, Part.micLeftGain, Part.micRightGain])
            cameraSection
            leftovers
        }
    }

    // ── الكاميرا: مدخل للنظر، وبعده الإعدادات ───────────────────────────────
    //
    // «التقط صورة» كزرّ بقائمة إعدادات كان بيشتغل مضبوط وما بيوريك إشي — الأمر
    // بيوصل والصورة بترجع وبتنرمى. فالمدخل للعرض صار أول إشي بالقسم، والإعدادات
    // (فلاش، دقّة) تحته: بتفتح الكاميرا عشان تشوف، مش عشان تظبّط.
    @ViewBuilder
    private var cameraSection: some View {
        let settings = [Part.camFlash, Part.camFlashLvl,
                        Part.camFlashMode, Part.camFrameSize, Part.camQuality]
            .compactMap { name in store.robotDevices.first { $0.name == name } }
        let hasCamera = !settings.isEmpty
            || store.robotDevices.contains { $0.name == Part.camSnapshot }

        if hasCamera, let node = store.nodes.first {
            card("robot.control.camera", icon: "camera.fill", hint: "robot.control.camera.hint") {
                NavigationLink {
                    CameraView(node: node)
                        .environmentObject(state)
                        .environmentObject(lang)
                } label: {
                    HStack(spacing: Theme.Spacing.md) {
                        Image(systemName: "eye.circle.fill")
                            .scaledFont(Theme.Icon.lg)
                            .foregroundColor(Theme.Colors.accent)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(lang.s("robot.control.camera.open"))
                                .font(Theme.Typography.headline)
                                .foregroundColor(Theme.Colors.primaryText)
                            Text(lang.s("robot.control.camera.open.hint"))
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.secondaryText)
                        }
                        Spacer(minLength: 0)
                        Image(systemName: "chevron.forward")
                            .scaledFont(Theme.Icon.sm, weight: .semibold)
                            .foregroundColor(Theme.Colors.tertiaryText)
                    }
                    .sandyCard()
                }
                .buttonStyle(.plain)

                ForEach(settings) { device in
                    DeviceCard(device: device, store: store)
                }
            }
        }
    }

    // ── الشاشة: نص + صورة ────────────────────────────────────────────────────
    //
    // الصورة مش بطاقة جهاز لأنها مش أمر: بتختار من ألبومك، وبيروح رفع، والخادم
    // بيصغّرها ويحوّلها لبكسلات الشاشة قبل ما توصل اللوح. فحطّيتها جنب حقل
    // النص — نفس القسم، لأنه التنين بيروحوا ع نفس المكان: وشها.
    @ViewBuilder
    private var screenSection: some View {
        if let screen = store.robotDevices.first(where: { $0.name == Part.screen }) {
            card("robot.control.screen", icon: "textformat", hint: "robot.control.screen.hint") {
                DeviceCard(device: screen, store: store)

                // PhotosPicker builds its label off the main actor: resolve first.
                let pickTitle = lang.s(sendingImage ? "robot.control.image.sending"
                                                    : "robot.control.image.pick")
                PhotosPicker(selection: $pickedImage, matching: .images) {
                    HStack(spacing: Theme.Spacing.sm) {
                        Image(systemName: sendingImage
                              ? "arrow.triangle.2.circlepath" : "photo.on.rectangle")
                            .scaledFont(Theme.Icon.md, weight: .semibold)
                        Text(pickTitle)
                            .font(Theme.Typography.button)
                    }
                    .foregroundColor(Theme.Colors.accent)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Spacing.md)
                    .background(Theme.Colors.surface)
                    .cornerRadius(Theme.Radius.card)
                }
                .disabled(store.demo || sendingImage)

                if !imageNotice.isEmpty {
                    SandyNotice(imageNotice, kind: .gentleWarning)
                }
            }
            .onChange(of: pickedImage) { _, item in
                Task { await upload(item, to: screen) }
            }
        }
    }

    private func upload(_ item: PhotosPickerItem?, to device: DeviceItem) async {
        guard let item else { return }
        sendingImage = true
        imageNotice = ""
        defer { sendingImage = false; pickedImage = nil }
        do {
            // A small JPEG made here: an iPhone photo is HEIC (the server cannot open it) and
            // full size is past its 8 MB; the screen is 240 px, so 480 is plenty.
            guard let data = try await item.loadTransferable(type: Data.self),
                  let jpeg = ImageDownscale.jpeg(from: data, maxPixel: 480) else {
                imageNotice = lang.s("robot.control.image.unreadable")
                return
            }
            try await state.api.sendDeviceImage(name: device.name, jpegData: jpeg)
        } catch {
            // الصورة بتمشي ع عشرين رسالة، فالفشل بنصّها وارد. نقولها بدل ما
            // نسكت — «ما ظهرت» و«انقطعت بالنص» مشكلتان مختلفتان.
            imageNotice = lang.s("robot.control.image.failed")
        }
    }

    // ── أقسام ────────────────────────────────────────────────────────────────

    /// قسم واحد. ما بيظهر إذا ولا وحدة من قطعه موجودة — لوح بلا كاميرا ما إله
    /// عنوان «كاميرا» فاضي تحته.
    @ViewBuilder
    private func section(_ titleKey: String, icon: String, hint hintKey: String,
                         parts: [String]) -> some View {
        let present = parts.compactMap { name in
            store.robotDevices.first { $0.name == name }
        }
        if !present.isEmpty {
            card(titleKey, icon: icon, hint: hintKey) {
                ForEach(present) { device in
                    DeviceCard(device: device, store: store)
                }
            }
        }
    }

    /// أي قطعة أعلنها اللوح وما إلها مكان بالأقسام فوق ولا بالأزرار السريعة.
    ///
    /// موجود عشان فيرموير أحدث من التطبيق ما يخلّي قطعة تختفي بصمت. تظهر تحت
    /// عنوان عام — أقل جمالًا من مكانها الصح، وأصدق بكتير من غيابها.
    @ViewBuilder
    private var leftovers: some View {
        let placed: Set<String> = Part.quick.union([
            Part.head, Part.screen,
            Part.volume, Part.speakerTest,
            Part.micLeft, Part.micRight, Part.micLeftGain, Part.micRightGain,
            Part.camFlash, Part.camFlashLvl, Part.camFlashMode,
            Part.camSnapshot, Part.camStream, Part.camFrameSize, Part.camQuality,
        ])
        let rest = store.robotDevices.filter { !placed.contains($0.name) }
        if !rest.isEmpty {
            card("robot.control.other", icon: "ellipsis.circle", hint: nil) {
                ForEach(rest) { device in
                    DeviceCard(device: device, store: store)
                }
            }
        }
    }

    /// A section in the same card as the quick buttons above: a title, a line on it, its parts.
    private func card<Content: View>(_ titleKey: String, icon: String, hint hintKey: String?,
                                     @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Label(lang.s(titleKey), systemImage: icon)
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
            if let hintKey {
                Text(lang.s(hintKey))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
            }
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .sandyCard(.secondary)
    }
}
