import SwiftUI

/// شاشة متقدّمة (داخل أرشيف الحساب): يختار المستخدم لهجة ساندي و/أو يكتب تعليمات
/// مخصّصة لأسلوبها. لو ما لمس شي، تضل ساندي بشخصيتها اللطيفة الافتراضية — هالشاشة
/// اختيارية بالكامل. هويتها الفلسطينية ثابتة دايماً ومش معروضة هون لأنها غير قابلة للتغيير.
struct PersonaView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var form = PersonaForm()

    var body: some View {
        ZStack {
            SandyBackground()

            ScrollView {
                VStack(spacing: Theme.Spacing.lg) {
                    Text(lang.s("persona.intro"))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .multilineTextAlignment(.leading)
                        .frame(maxWidth: .infinity, alignment: .leading)

                    dialectCard
                    customInstructionsCard

                    if form.savedNotice { SandyNotice(lang.s("persona.saved"), kind: .info) }
                    if !form.errorKey.isEmpty { SandyNotice(lang.s(form.errorKey), kind: .gentleWarning) }

                    if form.loadFailed {
                        // Nothing was read: saving now would write the defaults over what is kept.
                        SandyButton(title: lang.s("common.retry"), systemImage: "arrow.clockwise",
                                   style: .primary, fillWidth: true) {
                            Task { await form.load(api: state.api) }
                        }
                        .disabled(form.loading)
                    } else {
                        SandyButton(title: form.saving ? "..." : lang.s("persona.save"),
                                   systemImage: "checkmark.circle.fill",
                                   style: .primary, fillWidth: true) { form.save(api: state.api) }
                            .disabled(!form.canSave)

                        if form.loaded && (!form.customInstructions.isEmpty || form.dialect != "palestinian") {
                            SandyButton(title: lang.s("persona.reset"), systemImage: "arrow.counterclockwise",
                                       style: .secondary, fillWidth: true) { form.reset(api: state.api) }
                                .disabled(!form.canSave)
                        }
                    }
                }
                .padding(Theme.Spacing.md)
            }
        }
        .navigationTitle(lang.s("persona.title"))
        .navigationBarTitleDisplayMode(.inline)
        .task { await form.load(api: state.api) }
    }

    private var dialectCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                SectionHeader(title: lang.s("persona.dialectLabel"))
                Picker(lang.s("persona.dialectLabel"), selection: $form.dialect) {
                    ForEach(form.availableDialects) { option in
                        Text(option.label).tag(option.key)
                    }
                }
                .pickerStyle(.segmented)
                .disabled(!form.loaded || form.availableDialects.isEmpty)
            }
        }
    }

    private var customInstructionsCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                SectionHeader(title: lang.s("persona.customLabel"))
                ZStack(alignment: .topLeading) {
                    if form.customInstructions.isEmpty {
                        Text(lang.s("persona.customPlaceholder"))
                            .font(Theme.Typography.body)
                            .foregroundColor(Theme.Colors.tertiaryText)
                            .padding(.horizontal, Theme.Spacing.sm)
                            .padding(.vertical, Theme.Spacing.sm)
                    }
                    TextEditor(text: $form.customInstructions)
                        .font(Theme.Typography.body)
                        .frame(minHeight: 110)
                        .scrollContentBackground(.hidden)
                        .disabled(!form.loaded)
                }
                .padding(Theme.Spacing.xs)
                .background(Theme.Colors.surface)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))

                Text(lang.s("persona.customHint"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.tertiaryText)
            }
        }
    }
}

/// What the persona screen holds. Nothing can be saved until the saved persona was read:
/// after a failed load the fields hold the defaults, and saving them wrote over the user's own.
@MainActor
final class PersonaForm: ObservableObject {
    @Published var dialect = "palestinian"
    @Published var customInstructions = ""
    @Published private(set) var availableDialects: [DialectOption] = []
    @Published private(set) var loading = false
    @Published private(set) var loaded = false
    @Published private(set) var loadFailed = false
    @Published private(set) var saving = false
    @Published private(set) var savedNotice = false
    /// A localization key, empty when there is nothing to say.
    @Published private(set) var errorKey = ""

    var canSave: Bool { loaded && !saving }

    func load(api: APIClient) async {
        loading = true
        defer { loading = false }
        do {
            let persona = try await api.getPersona()
            dialect = persona.dialect
            customInstructions = persona.customInstructions
            availableDialects = persona.availableDialects
            loaded = true
            loadFailed = false
            errorKey = ""
        } catch {
            if !loaded { loadFailed = true }
            errorKey = "persona.loadError"
        }
    }

    func save(api: APIClient) {
        guard canSave else { return }
        saving = true
        withAnimation { errorKey = ""; savedNotice = false }
        Task {
            do {
                try await api.savePersona(dialect: dialect, customInstructions: customInstructions)
                withAnimation { savedNotice = true }
            } catch {
                withAnimation { errorKey = "persona.saveError" }
            }
            saving = false
        }
    }

    func reset(api: APIClient) {
        guard canSave else { return }
        dialect = "palestinian"
        customInstructions = ""
        save(api: api)
    }
}
