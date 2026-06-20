import SwiftUI
import AuthenticationServices

struct AuthView: View {
    @EnvironmentObject var state: AppState
    @State private var password = ""
    @State private var error = ""
    @State private var loading = false

    var body: some View {
        VStack(spacing: 18) {
            Spacer()
            Text("ساندي").font(.largeTitle).bold()
            Text("سكرتيرك الشخصي").foregroundColor(.secondary)

            TextField("عنوان الخادم", text: $state.baseURL)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()

            SignInWithAppleButton(.signIn,
                onRequest: { $0.requestedScopes = [.fullName, .email] },
                onCompletion: handleApple)
                .frame(height: 48)
                .signInWithAppleButtonStyle(.black)

            Divider().padding(.vertical, 6)
            Text("أو دخول المطوّر (للتجربة)").font(.caption).foregroundColor(.secondary)
            SecureField("كلمة سر المالك", text: $password).textFieldStyle(.roundedBorder)
            Button(action: devLogin) {
                Text(loading ? "..." : "دخول").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(loading)

            if !error.isEmpty { Text(error).foregroundColor(.red).font(.caption) }
            Spacer()
        }
        .padding()
    }

    private func devLogin() {
        loading = true; error = ""
        Task {
            do {
                try await state.api.devLogin(password: password)
                let ob = try await state.api.getOnboarding()
                state.routeAfterAuth(onboardingDone: ob.done)
            } catch { self.error = error.localizedDescription }
            loading = false
        }
    }

    private func handleApple(_ result: Result<ASAuthorization, Error>) {
        guard case let .success(authResult) = result,
              let cred = authResult.credential as? ASAuthorizationAppleIDCredential,
              let data = cred.identityToken,
              let idToken = String(data: data, encoding: .utf8) else {
            error = "فشل تسجيل الدخول بآبل"; return
        }
        let name = [cred.fullName?.givenName, cred.fullName?.familyName]
            .compactMap { $0 }.joined(separator: " ")
        Task {
            do {
                let done = try await state.api.signInApple(idToken: idToken, name: name)
                state.routeAfterAuth(onboardingDone: done)
            } catch { self.error = error.localizedDescription }
        }
    }
}
