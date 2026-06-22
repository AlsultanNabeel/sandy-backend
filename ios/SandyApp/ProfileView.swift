import SwiftUI

/// تبويب حسابي — هوية دافئة: أفاتار ساندي + الاسم المفضّل + الاهتمامات (شارات)
/// + تعديل الملف بشيت أنيق + تسجيل خروج. كله بنظام تصميم ساندي (Theme/Components).
struct ProfileView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @State private var showEdit = false
    /// لإظهار الشارات بحركة لطيفة عند الدخول.
    @State private var appeared = false

    /// الاسم المعروض: المفضّل ← الاسم ← افتراضي ودّي.
    private var displayName: String {
        let preferred = state.onboarding.preferredName.trimmingCharacters(in: .whitespaces)
        if !preferred.isEmpty { return preferred }
        let name = state.onboarding.name.trimmingCharacters(in: .whitespaces)
        return name.isEmpty ? lang.s("profile.nameFallback") : name
    }

    private var interests: [String] { state.onboarding.interests }

    var body: some View {
        ZStack {
            SandyBackground()

            ScrollView {
                VStack(spacing: Theme.Spacing.lg) {
                    header
                    preferredNameCard
                    interestsCard
                    languageCard
                    editButton
                    signOutButton
                }
                .padding(Theme.Spacing.md)
            }
        }
        .navigationTitle(lang.s("profile.title"))
        .task { await state.refreshOnboarding() }
        .onAppear {
            withAnimation(.spring(response: 0.55, dampingFraction: 0.8)) { appeared = true }
        }
        .sheet(isPresented: $showEdit) {
            EditProfileSheet(
                preferredName: state.onboarding.preferredName,
                interests: state.onboarding.interests
            ) { name, items in
                try await state.saveProfile(preferredName: name, interests: items)
            }
        }
    }

    // MARK: - الترويسة الدافئة

    private var header: some View {
        VStack(spacing: Theme.Spacing.md) {
            SandyAvatar(size: 96, mood: .happy)
                .scaleEffect(appeared ? 1 : 0.85)
                .opacity(appeared ? 1 : 0)
                .animation(.spring(response: 0.6, dampingFraction: 0.7), value: appeared)

            VStack(spacing: Theme.Spacing.xs) {
                Text(displayName)
                    .font(Theme.Typography.largeTitle)
                    .foregroundColor(Theme.Colors.primaryText)
                    .multilineTextAlignment(.center)

                Text(lang.s("profile.subtitle"))
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Spacing.lg)
    }

    // MARK: - بطاقة الاسم المفضّل

    private var preferredNameCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                SectionHeader(title: lang.s("profile.preferredName"))
                Text(displayName)
                    .font(Theme.Typography.title)
                    .foregroundColor(Theme.Colors.accentDeep)
            }
        }
    }

    // MARK: - بطاقة الاهتمامات

    private var interestsCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                SectionHeader(title: lang.s("profile.interests"))
                if interests.isEmpty {
                    SandyNotice(lang.s("profile.interestsEmpty"),
                                kind: .info)
                } else {
                    ChipFlow(items: interests) { item in
                        InterestChip(text: item, appeared: appeared)
                    }
                }
            }
        }
    }

    // MARK: - بطاقة اللغة

    private var languageCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                SectionHeader(title: lang.s("common.language"))
                LanguageToggle()
            }
        }
    }

    // MARK: - الأزرار

    private var editButton: some View {
        SandyButton(title: lang.s("profile.edit"), systemImage: "pencil",
                    style: .primary, fillWidth: true) {
            showEdit = true
        }
    }

    private var signOutButton: some View {
        SandyButton(title: lang.s("profile.signOut"), systemImage: "rectangle.portrait.and.arrow.right",
                    style: .secondary, fillWidth: true) {
            state.signOut()
        }
        .padding(.top, Theme.Spacing.xs)
    }
}

// MARK: - شارة اهتمام (للعرض) — تطلع بحركة لطيفة

/// شارة اهتمام بنكهة مرجانية ساندي، تظهر بنعومة عند الدخول.
private struct InterestChip: View {
    let text: String
    let appeared: Bool

    var body: some View {
        Text(text)
            .font(Theme.Typography.callout)
            .foregroundColor(Theme.Colors.accentDeep)
            .padding(.horizontal, Theme.Spacing.md)
            .padding(.vertical, Theme.Spacing.sm)
            .background(Theme.Colors.accent.opacity(0.14))
            .clipShape(Capsule())
            .overlay(Capsule().stroke(Theme.Colors.accent.opacity(0.25), lineWidth: 1))
            .scaleEffect(appeared ? 1 : 0.6)
            .opacity(appeared ? 1 : 0)
            .animation(.spring(response: 0.5, dampingFraction: 0.7), value: appeared)
    }
}

// MARK: - تخطيط ملتفّ للشارات (iOS 16: حساب يدوي للأسطر)

/// يلفّ العناصر على أكثر من سطر حسب العرض المتاح — بديل خفيف عن FlowLayout
/// (المتوفّر بـ iOS 16). يقيس عرض الحاوية ويوزّع الشارات يدويًا.
private struct ChipFlow<Item: Hashable, Content: View>: View {
    let items: [Item]
    let content: (Item) -> Content

    @State private var totalHeight: CGFloat = 0

    var body: some View {
        GeometryReader { geo in
            generate(in: geo)
        }
        .frame(height: totalHeight)
    }

    private func generate(in geo: GeometryProxy) -> some View {
        var x: CGFloat = 0
        var y: CGFloat = 0

        return ZStack(alignment: .topLeading) {
            ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                content(item)
                    .alignmentGuide(.leading) { dimension in
                        if abs(x - dimension.width) > geo.size.width {
                            x = 0
                            y -= dimension.height + Theme.Spacing.sm
                        }
                        let result = x
                        if index == items.count - 1 {
                            x = 0
                        } else {
                            x -= dimension.width + Theme.Spacing.sm
                        }
                        return result
                    }
                    .alignmentGuide(.top) { _ in
                        let result = y
                        if index == items.count - 1 {
                            y = 0
                        }
                        return result
                    }
            }
        }
        .background(heightReader)
    }

    private var heightReader: some View {
        GeometryReader { geo -> Color in
            DispatchQueue.main.async {
                if totalHeight != geo.size.height {
                    totalHeight = geo.size.height
                }
            }
            return Color.clear
        }
    }
}

// MARK: - شيت تعديل الملف

/// شيت تعديل: الاسم المفضّل + الاهتمامات (إضافة/حذف بشارات). الحفظ async،
/// والفشل يطلع كـ SandyNotice ودّي (مو سطر أحمر). النجاح يقفل الشيت.
private struct EditProfileSheet: View {
    @EnvironmentObject var lang: LanguageManager
    @Environment(\.dismiss) private var dismiss
    /// يستقبل (الاسم المفضّل، الاهتمامات) ويرمي عند الفشل.
    let onSave: (String, [String]) async throws -> Void

    @State private var preferredName: String
    @State private var interests: [String]
    @State private var newInterest = ""
    @State private var saving = false
    @State private var errorMessage = ""

    @FocusState private var addFieldFocused: Bool

    init(preferredName: String, interests: [String],
         onSave: @escaping (String, [String]) async throws -> Void) {
        self.onSave = onSave
        _preferredName = State(initialValue: preferredName)
        _interests = State(initialValue: interests)
    }

    private var canAdd: Bool {
        !newInterest.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        NavigationStack {
            ZStack {
                SandyBackground()

                ScrollView {
                    VStack(spacing: Theme.Spacing.lg) {
                        nameSection
                        interestsSection
                        if !errorMessage.isEmpty {
                            SandyNotice(errorMessage, kind: .gentleWarning)
                                .transition(.opacity.combined(with: .move(edge: .top)))
                        }
                    }
                    .padding(Theme.Spacing.md)
                }
            }
            .navigationTitle(lang.s("profile.edit"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("common.cancel")) { dismiss() }
                        .disabled(saving)
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(lang.s("common.save")) { save() }
                        .font(Theme.Typography.button)
                        .disabled(saving)
                }
            }
        }
    }

    // MARK: أقسام الشيت

    private var nameSection: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                SectionHeader(title: lang.s("profile.preferredNameEdit"))
                TextField(lang.s("profile.namePlaceholder"), text: $preferredName)
                    .font(Theme.Typography.body)
                    .padding(Theme.Spacing.md)
                    .background(Theme.Colors.surface)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                    .disabled(saving)
            }
        }
    }

    private var interestsSection: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                SectionHeader(title: lang.s("profile.interests"))

                if interests.isEmpty {
                    Text(lang.s("profile.interestsHint"))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)
                } else {
                    ChipFlow(items: interests) { item in
                        EditableChip(text: item) { remove(item) }
                    }
                }

                HStack(spacing: Theme.Spacing.sm) {
                    TextField(lang.s("profile.addInterest"), text: $newInterest)
                        .font(Theme.Typography.body)
                        .focused($addFieldFocused)
                        .submitLabel(.done)
                        .onSubmit { addInterest() }
                        .padding(Theme.Spacing.md)
                        .background(Theme.Colors.surface)
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
                        .disabled(saving)

                    Button {
                        addInterest()
                    } label: {
                        Image(systemName: "plus.circle.fill")
                            .font(.system(size: 28))
                            .foregroundColor(canAdd ? Theme.Colors.accent : Theme.Colors.secondaryText.opacity(0.4))
                    }
                    .buttonStyle(.plain)
                    .disabled(!canAdd || saving)
                }
            }
        }
    }

    // MARK: منطق

    private func addInterest() {
        let item = newInterest.trimmingCharacters(in: .whitespaces)
        guard !item.isEmpty, !interests.contains(item) else {
            newInterest = ""
            return
        }
        withAnimation(.spring(response: 0.4, dampingFraction: 0.75)) {
            interests.append(item)
        }
        newInterest = ""
        addFieldFocused = true
    }

    private func remove(_ item: String) {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
            interests.removeAll { $0 == item }
        }
    }

    private func save() {
        saving = true
        withAnimation { errorMessage = "" }
        let name = preferredName.trimmingCharacters(in: .whitespaces)
        let cleaned = interests
        Task {
            do {
                try await onSave(name, cleaned)
                dismiss()
            } catch {
                withAnimation {
                    errorMessage = lang.s("profile.saveFailed")
                }
            }
            saving = false
        }
    }
}

// MARK: - شارة قابلة للحذف (داخل الشيت)

/// شارة اهتمام فيها زر حذف صغير — للاستعمال داخل شيت التعديل.
private struct EditableChip: View {
    let text: String
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: Theme.Spacing.xs) {
            Text(text)
                .font(Theme.Typography.callout)
                .foregroundColor(Theme.Colors.accentDeep)
            Button(action: onDelete) {
                Image(systemName: "xmark.circle.fill")
                    .font(.system(size: 16))
                    .foregroundColor(Theme.Colors.accentDeep.opacity(0.6))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.vertical, Theme.Spacing.sm)
        .background(Theme.Colors.accent.opacity(0.14))
        .clipShape(Capsule())
        .overlay(Capsule().stroke(Theme.Colors.accent.opacity(0.25), lineWidth: 1))
    }
}
