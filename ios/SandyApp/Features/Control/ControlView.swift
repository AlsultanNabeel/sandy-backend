import SwiftUI

/// شاشة التحكّم بالبيت — نظام الإضافات المعتمد على البيانات: تربط وحدة ساندي،
/// تضيف أجهزة حقيقية، وتتحكّم فيها. كل جهاز يرسم أداة التحكّم المناسبة لنوعه
/// (مفتاح/إضاءة/ستارة/وسائط/خيارات/ريموت). نفس وصفة ساندي: ستور يملك الحقيقة،
/// تحديث متفائل ثم مصالحة، وأخطاء بصوت ساندي عبر SandyNotice.
struct ControlView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store = DevicesStore()

    @State private var showAddDevice = false
    @State private var editingDevice: DeviceItem?
    @State private var showPairNode = false
    @State private var renamingNode: NodeItem?

    var body: some View {
        ZStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.section) {
                    if store.demo { DemoBanner() }

                    if !store.notice.isEmpty {
                        SandyNotice(store.notice, kind: .gentleWarning)
                            .transition(.move(edge: .top).combined(with: .opacity))
                    }

                    content

                    // مساحة سفلية حتى ما يغطّي الزرّ العائم آخر بطاقة.
                    Color.clear.frame(height: Theme.Spacing.xxl + Theme.Spacing.xl)
                }
                .padding(Theme.Spacing.md)
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            // زر إضافة جهاز — عائم بالأسفل (يظهر فقط لمّا في وحدة مربوطة وبيانات حقيقية).
            if !store.demo && !store.nodes.isEmpty {
                VStack {
                    Spacer()
                    SandyButton(title: lang.s("control.device.add"),
                                systemImage: "plus.circle.fill",
                                fillWidth: true) {
                        showAddDevice = true
                    }
                    .padding(.horizontal, Theme.Spacing.lg)
                    .padding(.bottom, Theme.Spacing.lg)
                }
            }
        }
        .navigationTitle(lang.s("control.title"))
        .fullScreenCover(isPresented: $showAddDevice) {
            DeviceSheet(nodes: store.nodes) { draft in
                try await store.add(api: state.api, draft: draft)
            }
            .environmentObject(state)
            .environmentObject(lang)
        }
        .fullScreenCover(item: $editingDevice) { device in
            DeviceSheet(nodes: store.nodes, existing: device) { draft in
                try await store.update(api: state.api, device: device, draft: draft)
            }
            .environmentObject(state)
            .environmentObject(lang)
        }
        .fullScreenCover(isPresented: $showPairNode) {
            NodePairSheet { code, label in
                try await store.pair(api: state.api, code: code, label: label)
            }
            .environmentObject(lang)
        }
        .fullScreenCover(item: $renamingNode) { node in
            NodeRenameSheet(existing: node) { label in
                try await store.rename(api: state.api, node: node, label: label)
            }
            .environmentObject(lang)
        }
        .task { await store.load(api: state.api) }
        .refreshable { await store.load(api: state.api) }
        .animation(.spring(response: 0.45, dampingFraction: 0.82), value: store.devices.map(\.id))
        .animation(.easeInOut(duration: 0.25), value: store.notice)
    }

    // ── المحتوى: تحميل / فاضي / أقسام ──────────────────────────────────────
    @ViewBuilder
    private var content: some View {
        if store.loading && store.devices.isEmpty && store.nodes.isEmpty {
            loadingState
        } else {
            robotLink
            devicesSection
            nodesSection
        }
    }

    private var loadingState: some View {
        VStack(spacing: Theme.Spacing.md) {
            ProgressView().tint(Theme.Colors.accent)
            Text(lang.s("control.loading"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Spacing.xxl)
    }

    // MARK: - مدخل صفحة الروبوت

    /// جسم ساندي إله صفحته. هون بس المدخل.
    ///
    /// كان كل شي بقائمة وحدة: رقبتها ووشها ومايكاتها بين لمبة الصالة والمروحة.
    /// هدول إشيان مختلفان — الأول جسمها والتاني بيتك — وبطاقة وحدة بتوصلك
    /// للأول بتخلّي هاي الصفحة عن البيت فعلًا.
    @ViewBuilder
    private var robotLink: some View {
        if !store.robotDevices.isEmpty {
            NavigationLink {
                RobotControlView(store: store)
                    .environmentObject(state)
                    .environmentObject(lang)
            } label: {
                HStack(spacing: Theme.Spacing.md) {
                    Image(systemName: "figure.wave.circle.fill")
                        .font(.system(size: Theme.Icon.lg))
                        .foregroundColor(Theme.Colors.accent)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(lang.s("robot.control.title"))
                            .font(Theme.Typography.headline)
                            .foregroundColor(Theme.Colors.primaryText)
                        Text(String(format: lang.s("robot.control.count"),
                                    store.robotDevices.count))
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.forward")
                        .font(.system(size: Theme.Icon.sm, weight: .semibold))
                        .foregroundColor(Theme.Colors.tertiaryText)
                }
                .sandyCard()
            }
            .buttonStyle(.plain)
        }
    }

    // MARK: - قسم الأجهزة (مجموعة حسب الغرفة)

    @ViewBuilder
    private var devicesSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            SectionHeader(title: lang.s("control.section.devices"))

            if store.devices.isEmpty {
                deviceEmptyState
            } else {
                ForEach(store.roomGroups, id: \.room) { group in
                    VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                        Text(group.room.isEmpty ? lang.s("control.noRoom") : group.room)
                            .font(Theme.Typography.callout)
                            .foregroundColor(Theme.Colors.secondaryText)
                        ForEach(group.devices) { device in
                            DeviceCard(device: device, store: store,
                                       onEdit: { editingDevice = device })
                        }
                    }
                }
            }
        }
    }

    private var deviceEmptyState: some View {
        VStack(spacing: Theme.Spacing.md) {
            SandyAvatar(size: 64, mood: .happy)
            Text(lang.s("control.devices.empty.title"))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
            Text(lang.s("control.devices.empty.hint"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Spacing.lg)
    }

    // MARK: - قسم وحدات ساندي

    @ViewBuilder
    private var nodesSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            HStack {
                SectionHeader(title: lang.s("control.section.nodes"))
                Spacer(minLength: 0)
                if !store.demo {
                    Button {
                        showPairNode = true
                    } label: {
                        HStack(spacing: Theme.Spacing.xs) {
                            Image(systemName: "plus")
                                .font(.system(size: Theme.Icon.sm, weight: .bold))
                            Text(lang.s("control.node.pair"))
                                .font(Theme.Typography.callout)
                        }
                        .foregroundColor(Theme.Colors.accent)
                    }
                    .buttonStyle(.plain)
                }
            }

            if store.nodes.isEmpty {
                nodeEmptyState
            } else {
                ForEach(store.nodes) { node in
                    NodeCard(node: node, store: store,
                             onRename: { renamingNode = node })
                }
            }
        }
    }

    private var nodeEmptyState: some View {
        VStack(spacing: Theme.Spacing.md) {
            SandyAvatar(size: 56, mood: .soft)
            Text(lang.s("control.nodes.empty.title"))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
            Text(lang.s("control.nodes.empty.hint"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            if !store.demo {
                SandyButton(title: lang.s("control.node.pair"),
                            systemImage: "antenna.radiowaves.left.and.right") {
                    showPairNode = true
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Spacing.lg)
    }
}

// ─────────────────────────────────────────────────────────────────────────
// MARK: - بطاقة جهاز (أداة التحكّم حسب النوع)

// ─────────────────────────────────────────────────────────────────────────
// MARK: - بطاقة وحدة ساندي

// ─────────────────────────────────────────────────────────────────────────
// MARK: - الستور (مصدر الحقيقة للأجهزة + الوحدات)

// ─────────────────────────────────────────────────────────────────────────
// MARK: - مسوّدة جهاز (حمولة الإضافة/التعديل من الشيت للستور)

// ─────────────────────────────────────────────────────────────────────────
// MARK: - شيت إضافة/تعديل جهاز

// ─────────────────────────────────────────────────────────────────────────
// MARK: - شيت ربط وحدة ساندي

// ─────────────────────────────────────────────────────────────────────────
// MARK: - شيت إعادة تسمية وحدة
