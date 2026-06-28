import SwiftUI
import AuthenticationServices

/// شاشة الدخول — مبنيّة بالكامل على نظام تصميم ساندي (خلفية أوبسيديان + بطاقة
/// زجاجية + أزرار/تنبيهات ساندي) بدل أدوات النظام المصمتة. الهيكل بسيط ومتدفّق
/// داخل `ScrollView` فيتصرّف سليم بكل المقاسات ومع ظهور الكيبورد (ما في عناصر
/// تتداخل ولا Spacers تطفو بلا اتزان).
struct AuthView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @State private var password = ""
    @State private var error = ""
    @State private var loading = false

    var body: some View {
        ZStack {
            SandyBackground()

            ScrollView {
                VStack(spacing: Theme.Spacing.lg) {
                    // أعلى الشاشة: مبدّل اللغة على الحافة الخلفية.
                    HStack {
                        Spacer()
                        LanguageToggle().frame(width: 120)
                    }

                    // الهوية: روبوت ساندي + الاسم + الشعار النصي.
                    VStack(spacing: Theme.Spacing.sm) {
                        SandyAvatar(size: 92, mood: .happy)
                        Text(lang.s("auth.title"))
                            .font(Theme.Typography.largeTitle)
                            .foregroundColor(Theme.Colors.primaryText)
                        Text(lang.s("auth.tagline"))
                            .font(Theme.Typography.subheadline)
                            .foregroundColor(Theme.Colors.secondaryText)
                    }
                    .padding(.top, Theme.Spacing.xl)

                    // بطاقة الدخول: عنوان الخادم + دخول آبل + دخول المطوّر.
                    SandyCard {
                        VStack(spacing: Theme.Spacing.md) {
                            TextField(lang.s("auth.serverUrl"), text: $state.baseURL)
                                .textFieldStyle(.plain)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .keyboardType(.URL)
                                .modifier(SandyField())

                            SignInWithAppleButton(.signIn,
                                onRequest: { $0.requestedScopes = [.fullName, .email] },
                                onCompletion: handleApple)
                                .frame(height: 50)
                                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control,
                                                            style: .continuous))
                                .signInWithAppleButtonStyle(.white)

                            // فاصل "أو دخول المطوّر" — خطّان رفيعان حول النص.
                            HStack(spacing: Theme.Spacing.sm) {
                                hairline
                                Text(lang.s("auth.devLogin"))
                                    .font(Theme.Typography.caption)
                                    .foregroundColor(Theme.Colors.secondaryText)
                                    .fixedSize()
                                hairline
                            }

                            SecureField(lang.s("auth.ownerPassword"), text: $password)
                                .textFieldStyle(.plain)
                                .textContentType(.password)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .submitLabel(.go)
                                // ضغطة الإدخال بالكيبورد تسجّل دخول مباشرة.
                                .onSubmit { devLogin() }
                                .modifier(SandyField())

                            SandyButton(title: lang.s("auth.login"),
                                        systemImage: "arrow.right.circle.fill",
                                        isLoading: loading,
                                        fillWidth: true) { devLogin() }

                            // الخطأ بصوت ساندي الدافئ بدل سطر أحمر صارخ.
                            if !error.isEmpty {
                                SandyNotice(error, kind: .gentleWarning)
                            }
                        }
                    }
                }
                .padding(Theme.Spacing.lg)
                // عمود محدود العرض موسّط — يتّزن على الآيباد والشاشات العريضة.
                .frame(maxWidth: 460)
                .frame(maxWidth: .infinity)
            }
        }
    }

    /// خطّ شعري رفيع لفاصل "أو دخول المطوّر".
    private var hairline: some View {
        Rectangle()
            .fill(Theme.Colors.border)
            .frame(height: 1)
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

// MARK: - حقل إدخال بنمط ساندي

/// خلفية/حدّ موحّد لحقول الإدخال (يقابل سطح الحقول بباقي الواجهات): سطح داكن +
/// حدّ كهربائي خفيف + حواف ناعمة. يُستعمل مع `.textFieldStyle(.plain)`.
private struct SandyField: ViewModifier {
    func body(content: Content) -> some View {
        content
            .foregroundColor(Theme.Colors.primaryText)
            .padding(.vertical, Theme.Spacing.md)
            .padding(.horizontal, Theme.Spacing.md)
            .background(Theme.Colors.surface)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                    .stroke(Theme.Colors.border, lineWidth: 1)
            )
    }
}
