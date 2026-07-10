import SwiftUI

/// شاشة متقدّمة (داخل أرشيف الحساب): يختار المستخدم لهجة ساندي و/أو يكتب تعليمات
/// مخصّصة لأسلوبها. لو ما لمس شي، تضل ساندي بشخصيتها اللطيفة الافتراضية — هالشاشة
/// اختيارية بالكامل. هويتها الفلسطينية ثابتة دايماً ومش معروضة هون لأنها غير قابلة للتغيير.
struct PersonaView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @State private var dialect = "palestinian"
    @State private var customInstructions = ""
    @State private var availableDialects: [DialectOption] = []
    @State private var loading = true
    @State private var saving = false
    @State private var savedNotice = false
    @State private var errorMessage = ""

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

                    if savedNotice { SandyNotice(lang.s("persona.saved"), kind: .info) }
                    if !errorMessage.isEmpty { SandyNotice(errorMessage, kind: .gentleWarning) }

                    SandyButton(title: saving ? "..." : lang.s("persona.save"),
                               systemImage: "checkmark.circle.fill",
                               style: .primary, fillWidth: true) { save() }
                        .disabled(saving || loading)

                    if !customInstructions.isEmpty || dialect != "palestinian" {
                        SandyButton(title: lang.s("persona.reset"), systemImage: "arrow.counterclockwise",
                                   style: .secondary, fillWidth: true) { reset() }
                            .disabled(saving || loading)
                    }
                }
                .padding(Theme.Spacing.md)
            }
        }
        .navigationTitle(lang.s("persona.title"))
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private var dialectCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                SectionHeader(title: lang.s("persona.dialectLabel"))
                Picker(lang.s("persona.dialectLabel"), selection: $dialect) {
                    ForEach(availableDialects) { option in
                        Text(option.label).tag(option.key)
                    }
                }
                .pickerStyle(.segmented)
                .disabled(loading || availableDialects.isEmpty)
            }
        }
    }

    private var customInstructionsCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                SectionHeader(title: lang.s("persona.customLabel"))
                ZStack(alignment: .topLeading) {
                    if customInstructions.isEmpty {
                        Text(lang.s("persona.customPlaceholder"))
                            .font(Theme.Typography.body)
                            .foregroundColor(Theme.Colors.tertiaryText)
                            .padding(.horizontal, Theme.Spacing.sm)
                            .padding(.vertical, Theme.Spacing.sm)
                    }
                    TextEditor(text: $customInstructions)
                        .font(Theme.Typography.body)
                        .frame(minHeight: 110)
                        .scrollContentBackground(.hidden)
                        .disabled(loading)
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

    private func load() async {
        loading = true
        do {
            let persona = try await state.api.getPersona()
            dialect = persona.dialect
            customInstructions = persona.customInstructions
            availableDialects = persona.availableDialects
        } catch {
            errorMessage = lang.s("persona.loadError")
        }
        loading = false
    }

    private func save() {
        saving = true
        withAnimation { errorMessage = ""; savedNotice = false }
        Task {
            do {
                try await state.api.savePersona(dialect: dialect, customInstructions: customInstructions)
                withAnimation { savedNotice = true }
            } catch {
                withAnimation { errorMessage = lang.s("persona.saveError") }
            }
            saving = false
        }
    }

    private func reset() {
        dialect = "palestinian"
        customInstructions = ""
        save()
    }
}
