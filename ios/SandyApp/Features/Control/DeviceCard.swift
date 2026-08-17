import SwiftUI

/// بطاقة جهاز واحد: ترويسة (اسم + غرفة + حالة الاتصال) + أداة التحكّم المناسبة
/// لنوعه. النقر المطوّل/القائمة السياقية تفتح التعديل أو الحذف.
struct DeviceCard: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    let device: DeviceItem
    @ObservedObject var store: DevicesStore
    @State private var draftText = ""
    let onEdit: () -> Void

    /// قيمة شريط الإضاءة المحلّية (نحرّكها بسلاسة قبل ما نرسل عند الإفلات).
    @State private var sliderValue: Double = 0
    /// تعلّم زر أشعة جديد (الاسم + فتح التنبيه).
    @State private var showLearn = false
    @State private var learnButtonName = ""

    /// قدّيش مساحة أعطاها المالك لهاي البطاقة (لما تكون جوّا لوح).
    @Environment(\.cardMetrics) private var metrics

    var body: some View {
        Group {
            if metrics.isCompact {
                compactBody
            } else {
                VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                    header
                    controlWidget
                }
            }
        }
        .sandyCard()
        .contextMenu {
            if !store.demo {
                Button { onEdit() } label: {
                    Label(lang.s("control.device.edit"), systemImage: "pencil")
                }
                Button(role: .destructive) {
                    store.delete(api: state.api, device: device)
                } label: { Label(lang.s("control.device.delete"), systemImage: "trash") }
            }
        }
        .onAppear { sliderValue = Double(Int(device.state) ?? device.dimmerMin) }
    }

    /// الشكل المربّع: الاسم كبير فوق، والتحكّم تحته — وبس.
    ///
    /// **هاد اللي طلبه المالك بالحرف**: بطاقة فيها مفتاح، لما تصغر، بتصير
    /// «مفتاح وفوقه اسمه، بس مفتاح واسم كبير».
    ///
    /// فالصفّ الأفقي بينكسر لعمود، وحالة الاتصال بتنشال — بمربّع، نقطة صغيرة
    /// وكلمة «متصل» بتاكل نص المساحة وما بتضيف إشي إنت مش شايفه أصلًا من كون
    /// التحكّم بيستجيب أو لأ. والاسم بيكبر مش بيصغر، لأنه بهالمقاس هو الإشي
    /// الوحيد اللي بيقولك شو هاد.
    private var compactBody: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            HStack(spacing: Theme.Spacing.sm) {
                Image(systemName: iconForType(device.controlType))
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(Theme.Colors.accent)
                Spacer(minLength: 0)
                Circle()
                    .fill(device.online ? Theme.Colors.success : Theme.Colors.tertiaryText)
                    .frame(width: 7, height: 7)
            }

            Text(device.label)
                .font(Theme.Typography.title)
                .foregroundColor(Theme.Colors.primaryText)
                .lineLimit(2)
                .minimumScaleFactor(0.8)

            Spacer(minLength: 0)

            controlWidget
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var header: some View {
        HStack(spacing: Theme.Spacing.md) {
            Image(systemName: iconForType(device.controlType))
                .font(.system(size: Theme.Icon.md, weight: .semibold))
                .foregroundColor(Theme.Colors.accent)
                .frame(width: 38, height: 38)
                .background(Theme.Colors.accent.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))

            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(device.label)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                onlineLabel
            }
            Spacer(minLength: 0)
        }
    }

    private var onlineLabel: some View {
        HStack(spacing: Theme.Spacing.xs) {
            Circle()
                .fill(device.online ? Theme.Colors.success : Theme.Colors.tertiaryText)
                .frame(width: 7, height: 7)
            Text(device.online ? lang.s("control.online") : lang.s("control.offline"))
                .font(Theme.Typography.caption)
                .foregroundColor(device.online ? Theme.Colors.success : Theme.Colors.tertiaryText)
        }
    }

    // ── أداة التحكّم حسب النوع ──
    @ViewBuilder
    private var controlWidget: some View {
        switch device.controlType {
        case "switch":  switchWidget
        case "dimmer":  dimmerWidget
        case "cover":   coverWidget
        case "media":   mediaWidget
        case "enum":    enumWidget
        case "ir":      irWidget
        case "text":    textWidget
        default:        unknownWidget
        }
    }

    // switch — تبديل on/off.
    private var switchWidget: some View {
        let isOn = device.state == "on"
        return Toggle(isOn: Binding(
            get: { isOn },
            set: { store.control(api: state.api, device: device, action: $0 ? "on" : "off") }
        )) {
            Text(isOn ? lang.s("control.action.on") : lang.s("control.action.off"))
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.secondaryText)
        }
        .tint(Theme.Colors.accent)
        .disabled(store.demo)
    }

    // dimmer — تبديل on/off + شريط قيمة (يُرسل set عند الإفلات).
    private var dimmerWidget: some View {
        let isOn = device.state != "off" && device.state != "0" && !device.state.isEmpty
        return VStack(spacing: Theme.Spacing.sm) {
            Toggle(isOn: Binding(
                get: { isOn },
                set: { store.control(api: state.api, device: device, action: $0 ? "on" : "off") }
            )) {
                Text(isOn ? lang.s("control.action.on") : lang.s("control.action.off"))
                    .font(Theme.Typography.callout)
                    .foregroundColor(Theme.Colors.secondaryText)
            }
            .tint(Theme.Colors.accent)
            .disabled(store.demo)

            HStack(spacing: Theme.Spacing.sm) {
                Text(lang.s("control.dimmer.level"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.tertiaryText)
                Slider(value: $sliderValue,
                       in: Double(device.dimmerMin)...Double(device.dimmerMax),
                       step: 1,
                       onEditingChanged: { editing in
                           // نرسل فقط عند انتهاء السحب — تفادي وابل طلبات.
                           if !editing {
                               store.control(api: state.api, device: device,
                                             action: "set", value: String(Int(sliderValue)))
                           }
                       })
                    .tint(Theme.Colors.accent)
                    .disabled(store.demo)
                Text("\(Int(sliderValue))")
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .monospacedDigit()
                    .frame(width: 34, alignment: .trailing)
            }
        }
    }

    // cover — افتح/سكّر/وقّف.
    private var coverWidget: some View {
        HStack(spacing: Theme.Spacing.sm) {
            controlButton(lang.s("control.action.open"), "arrow.up.to.line") {
                store.control(api: state.api, device: device, action: "open")
            }
            controlButton(lang.s("control.action.stop"), "stop.fill") {
                store.control(api: state.api, device: device, action: "stop")
            }
            controlButton(lang.s("control.action.close"), "arrow.down.to.line") {
                store.control(api: state.api, device: device, action: "close")
            }
        }
    }

    // media — شغّل/ثبّت/طفّي.
    private var mediaWidget: some View {
        HStack(spacing: Theme.Spacing.sm) {
            controlButton(lang.s("control.action.play"), "play.fill") {
                store.control(api: state.api, device: device, action: "on")
            }
            controlButton(lang.s("control.action.pause"), "pause.fill") {
                store.control(api: state.api, device: device, action: "pause")
            }
            controlButton(lang.s("control.action.off"), "power") {
                store.control(api: state.api, device: device, action: "off")
            }
        }
    }

    // enum — قائمة بخيارات meta.values (set + القيمة).
    @ViewBuilder
    private var enumWidget: some View {
        if device.enumValues.isEmpty {
            EmptyView()
        } else {
            // segmented لو الخيارات قليلة، وإلا قائمة منسدلة. نفصل الفرعين لأن
            // نمطي الـ Picker نوعان مختلفان لا يتوحّدان بمعامل شرطي واحد.
            let binding = Binding(
                get: { device.state.isEmpty ? (device.enumValues.first ?? "") : device.state },
                set: { store.control(api: state.api, device: device, action: "set", value: $0) }
            )
            if device.enumValues.count <= 3 {
                Picker("", selection: binding) {
                    ForEach(device.enumValues, id: \.self) { v in Text(v).tag(v) }
                }
                .pickerStyle(.segmented)
                .disabled(store.demo)
            } else {
                Picker("", selection: binding) {
                    ForEach(device.enumValues, id: \.self) { v in Text(v).tag(v) }
                }
                .pickerStyle(.menu)
                .disabled(store.demo)
            }
        }
    }

    // text — حقل حرّ + إرسال + إخفاء. للشاشة: اللي بتكتبه بيظهر ع وشها.
    //
    // مش قائمة خيارات لأنه اللي بينكتب ع وشها بتقرّره ساعتها إنت. وزرّ «شيله»
    // موجود بيّن جنبه لأنه الرسالة بتضل لحد ما تشيلها — وهاد مقصود: ملاحظة
    // بتختفي لحالها مش ملاحظة.
    @ViewBuilder
    private var textWidget: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            HStack(spacing: Theme.Spacing.sm) {
                TextField(device.textPlaceholder, text: $draftText, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...3)
                    .disabled(store.demo)
                    .submitLabel(.send)
                    .onSubmit { sendText() }

                Button { sendText() } label: {
                    Image(systemName: "paperplane.fill")
                        .font(.system(size: Theme.Icon.md, weight: .semibold))
                        .foregroundColor(draftText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                         ? Theme.Colors.tertiaryText : Theme.Colors.accent)
                }
                .buttonStyle(.plain)
                .disabled(store.demo || draftText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityLabel(lang.s("control.text.send"))
            }

            HStack(spacing: Theme.Spacing.md) {
                Button(lang.s("control.text.dismiss")) {
                    draftText = ""
                    store.control(api: state.api, device: device,
                                  action: "set", value: "dismiss")
                }
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
                .disabled(store.demo)

                Spacer(minLength: 0)

                // العدّ بالبايتات مش بالحروف: العربي متعدّد البايتات، والحدّ ع
                // اللوح ٢٥٥ بايت. عدّ الحروف بيوهم إنه في مساحة وما فيش.
                Text("\(draftText.utf8.count)/\(device.textMaxBytes)")
                    .font(Theme.Typography.caption.monospacedDigit())
                    .foregroundColor(draftText.utf8.count > device.textMaxBytes
                                     ? Theme.Colors.danger : Theme.Colors.tertiaryText)
            }
        }
    }

    private func sendText() {
        let text = draftText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text.utf8.count <= device.textMaxBytes else { return }
        store.control(api: state.api, device: device, action: "set", value: text)
    }

    // نوع ما بيعرفه هاد الإصدار من التطبيق.
    //
    // كان `default: switchWidget` — يعني أي نوع جديد بيرسم مفتاح تشغيل/إطفاء.
    // وهاد بالضبط اللي صار مع الشاشة: ظهرت كمفتاح، وكل ضغطة بترجع لحالها لأن
    // اللوح ما بيفهم «on». مفتاح بيكذب أسوأ من سطر بيقول ما بعرف.
    private var unknownWidget: some View {
        Text(String(format: lang.s("control.unknownType"), device.controlType))
            .font(Theme.Typography.caption)
            .foregroundColor(Theme.Colors.secondaryText)
    }

    // ir — أزرار من meta.buttons (send + اسم الزر) + تعلّم زر جديد عبر الوحدة.
    @ViewBuilder
    private var irWidget: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            if device.irButtonNames.isEmpty {
                Text(lang.s("control.ir.noButtons"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.tertiaryText)
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: Theme.Spacing.sm)],
                          spacing: Theme.Spacing.sm) {
                    ForEach(device.irButtonNames, id: \.self) { name in
                        controlButton(name, "dot.radiowaves.left.and.right") {
                            store.control(api: state.api, device: device, action: "send", value: name)
                        }
                    }
                }
            }

            if store.learning {
                HStack(spacing: Theme.Spacing.sm) {
                    ProgressView().tint(Theme.Colors.accent)
                    Text(lang.s("control.ir.learning"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
            } else if !store.demo {
                Button { showLearn = true } label: {
                    Label(lang.s("control.ir.learnNew"), systemImage: "plus.circle")
                        .font(Theme.Typography.callout)
                        .foregroundColor(Theme.Colors.accent)
                }
                .buttonStyle(.plain)
            }
        }
        .alert(lang.s("control.ir.learnNew"), isPresented: $showLearn) {
            TextField(lang.s("control.ir.learnPlaceholder"), text: $learnButtonName)
            Button(lang.s("control.ir.learnStart")) {
                store.learnIR(api: state.api, device: device, button: learnButtonName)
                learnButtonName = ""
            }
            Button(lang.s("common.cancel"), role: .cancel) { learnButtonName = "" }
        } message: {
            Text(lang.s("control.ir.learnAlertHint"))
        }
    }

    // زر تحكّم موحّد صغير (ثانوي).
    @ViewBuilder
    private func controlButton(_ title: String, _ icon: String,
                               action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: Theme.Spacing.xs) {
                Image(systemName: icon)
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                Text(title)
                    .font(Theme.Typography.caption)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
            .foregroundColor(Theme.Colors.accentDeep)
            .frame(maxWidth: .infinity)
            .padding(.vertical, Theme.Spacing.sm)
            .background {
                let shape = RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                ZStack {
                    shape.fill(.ultraThinMaterial)
                    shape.fill(Theme.Colors.accent.opacity(0.08))
                }
            }
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                    .stroke(Theme.Colors.accent.opacity(0.35), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .disabled(store.demo)
    }

    private func iconForType(_ type: String) -> String {
        switch type {
        case "switch": return "power"
        case "dimmer": return "lightbulb.fill"
        case "cover":  return "blinds.horizontal.closed"
        case "media":  return "music.note"
        case "enum":   return "slider.horizontal.3"
        case "ir":     return "dot.radiowaves.left.and.right"
        default:        return "switch.2"
        }
    }
}

/// بطاقة وحدة مربوطة: نقطة اتصال + اسم + عدد المخارج + الإصدار. القائمة السياقية
/// تعيد التسمية أو تفكّ الربط.
struct NodeCard: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    let node: NodeItem
    @ObservedObject var store: DevicesStore
    let onRename: () -> Void

    var body: some View {
        HStack(spacing: Theme.Spacing.md) {
            ZStack {
                Circle()
                    .fill(Theme.Colors.secondary.opacity(0.14))
                    .frame(width: 44, height: 44)
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .font(.system(size: Theme.Icon.md, weight: .semibold))
                    .foregroundColor(Theme.Colors.secondary)
            }
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(node.label)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                HStack(spacing: Theme.Spacing.sm) {
                    Circle()
                        .fill(node.online ? Theme.Colors.success : Theme.Colors.tertiaryText)
                        .frame(width: 7, height: 7)
                    Text(node.online ? lang.s("control.online") : lang.s("control.offline"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(node.online ? Theme.Colors.success : Theme.Colors.tertiaryText)
                    Text("•")
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.tertiaryText)
                    Text(String(format: lang.s("control.node.outputs"), "\(node.outputs.count)"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.tertiaryText)
                }
            }
            Spacer(minLength: 0)

            // فحص الجسم — بمكان بيّن ع البطاقة نفسها، مش مدفون بقائمة ضغطة
            // طويلة. لو ما حدا لاقاه، ما إله قيمة.
            if !store.demo {
                NavigationLink {
                    RobotTestView(store: store, node: node)
                } label: {
                    Image(systemName: "waveform.badge.magnifyingglass")
                        .font(.system(size: Theme.Icon.md, weight: .semibold))
                        .foregroundColor(Theme.Colors.accent)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(lang.s("robot.test.title"))
            }
        }
        .sandyCard()
        .contextMenu {
            if !store.demo {
                Button { onRename() } label: {
                    Label(lang.s("control.node.rename"), systemImage: "pencil")
                }
                Button(role: .destructive) {
                    store.unpair(api: state.api, node: node)
                } label: { Label(lang.s("control.node.unpair"), systemImage: "minus.circle") }
            }
        }
    }
}
