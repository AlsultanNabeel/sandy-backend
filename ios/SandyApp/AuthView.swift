import SwiftUI
import AuthenticationServices

struct AuthView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @State private var password = ""
    @State private var error = ""
    @State private var loading = false

    var body: some View {
        VStack(spacing: 18) {
            HStack { Spacer(); LanguageToggle().frame(width: 120) }
            Spacer()
            Text(lang.s("auth.title")).font(.largeTitle).bold()
            Text(lang.s("auth.tagline")).foregroundColor(.secondary)

            TextField(lang.s("auth.serverUrl"), text: $state.baseURL)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()

            SignInWithAppleButton(.signIn,
                onRequest: { $0.requestedScopes = [.fullName, .email] },
                onCompletion: handleApple)
                .frame(height: 48)
                .signInWithAppleButtonStyle(.black)

            Divider().padding(.vertical, 6)
            Text(lang.s("auth.devLogin")).font(.caption).foregroundColor(.secondary)
            SecureField(lang.s("auth.ownerPassword"), text: $password)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.go)
                // ضغطة الإدخال بالكيبورد تسجّل دخول مباشرة (مش لازم تضغط الزر).
                .onSubmit { devLogin() }
            Button(action: devLogin) {
                Text(loading ? "..." : lang.s("auth.login")).frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(loading)

            if !error.isEmpty { Text(error).foregroundColor(.red).font(.caption) }
            Spacer()
        }
        .padding()
    }

    private func devLogin() {
        // نتجنّب الإرسال المكرّر (زر + إدخال الكيبورد) أو كلمة سر فاضية.
        guard !loading, !password.isEmpty else { return }
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
            error = lang.s("auth.appleFailed"); return
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
