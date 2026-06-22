import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @State private var preferredName = ""
    @State private var interestsText = ""
    @State private var error = ""
    @State private var saving = false

    var body: some View {
        VStack(spacing: 18) {
            Spacer()
            Text(lang.s("onboarding.title")).font(.title).bold()

            VStack(alignment: .leading, spacing: 6) {
                Text(lang.s("onboarding.nameLabel"))
                TextField(lang.s("onboarding.namePlaceholder"), text: $preferredName).textFieldStyle(.roundedBorder)
            }
            VStack(alignment: .leading, spacing: 6) {
                Text(lang.s("onboarding.interestsLabel"))
                TextField(lang.s("onboarding.interestsPlaceholder"), text: $interestsText).textFieldStyle(.roundedBorder)
            }

            Button(action: save) {
                Text(saving ? "..." : lang.s("onboarding.save")).frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(saving || preferredName.isEmpty)

            if !error.isEmpty { Text(error).foregroundColor(.red).font(.caption) }
            Spacer()
        }
        .padding()
    }

    private func save() {
        saving = true; error = ""
        let interests = interestsText
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        Task {
            do {
                try await state.api.saveOnboarding(preferredName: preferredName, interests: interests)
                state.stage = .chat
            } catch { self.error = error.localizedDescription }
            saving = false
        }
    }
}
