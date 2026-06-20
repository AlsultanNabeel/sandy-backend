import SwiftUI

enum Stage { case auth, onboarding, chat }

@MainActor
final class AppState: ObservableObject {
    @Published var stage: Stage = .auth
    @Published var baseURL: String = "http://localhost:8080" {
        didSet { api.baseURL = baseURL }
    }
    let api = APIClient(baseURL: "http://localhost:8080")

    /// After a successful sign-in, go to onboarding (first time) or chat.
    func routeAfterAuth(onboardingDone: Bool) {
        stage = onboardingDone ? .chat : .onboarding
    }
}
