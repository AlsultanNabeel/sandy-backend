import SwiftUI
import AuthenticationServices

/// شاشة الدخول بنظام تصميم ساندي، داخل `ScrollView` حتى تتصرّف سليم مع الكيبورد.
struct AuthView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @State private var error = ""
    @State private var email = ""
    @State private var emailPassword = ""
    @State private var emailLoading = false
    @State private var appeared = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            SandyBackground()

            ScrollView {
                VStack(spacing: Theme.Spacing.lg) {
                    HStack {
                        Spacer()
                        LanguageToggle().frame(width: 120)
                    }

                    VStack(spacing: Theme.Spacing.sm) {
                        ZStack {
                            Circle()
                                .fill(RadialGradient(
                                    colors: [Theme.Colors.accent.opacity(0.22), .clear],
                                    center: .center, startRadius: 0, endRadius: 90))
                                .frame(width: 180, height: 180)
                            SandyAvatar(size: 104, mood: .happy)
                        }
                        .frame(height: 150)
                        .accessibilityHidden(true)

                        Text(lang.s("auth.title"))
                            .font(.system(.largeTitle, design: .rounded, weight: .bold))
                            .foregroundColor(Theme.Colors.primaryText)
                            .multilineTextAlignment(.center)
                        Text(lang.s("auth.tagline"))
                            .font(.body)
                            .foregroundColor(Theme.Colors.secondaryText)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.top, Theme.Spacing.lg)
                    .opacity(appeared ? 1 : 0)
                    .offset(y: appeared ? 0 : 10)

                    // بطاقة الدخول: أبل، جوجل، إيميل. حقل «عنوان الخادم» انشال عمدًا: كان بيقدر
                    // يوجّه كلمات السرّ والصوت ع خادم مش إلنا، وهو مكشوف قبل الدخول.
                    SandyCard {
                        VStack(spacing: Theme.Spacing.md) {
                            SignInWithAppleButton(.signIn,
                                onRequest: { $0.requestedScopes = [.fullName, .email] },
                                onCompletion: handleApple)
                                .frame(height: 50)
                                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control,
                                                            style: .continuous))
                                .signInWithAppleButtonStyle(.white)

                            Button { googleSignIn() } label: {
                                HStack(spacing: Theme.Spacing.sm) {
                                    Image(systemName: "g.circle.fill")
                                        .font(.system(size: Theme.Icon.md, weight: .semibold))
                                    Text(lang.lang == .ar ? "الدخول بجوجل" : "Sign in with Google")
                                        .font(Theme.Typography.button)
                                }
                                .foregroundColor(.black)
                                .frame(maxWidth: .infinity)
                                .frame(height: 50)
                                .background(Color.white)
                                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control,
                                                            style: .continuous))
                            }
                            .buttonStyle(.plain)

                            dividerLabel(lang.lang == .ar ? "أو بالإيميل" : "or with email")

                            TextField(lang.lang == .ar ? "الإيميل" : "Email", text: $email)
                                .textFieldStyle(.plain)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .keyboardType(.emailAddress)
                                .textContentType(.emailAddress)
                                .modifier(SandyField())

                            SecureField(lang.lang == .ar ? "كلمة السر" : "Password",
                                        text: $emailPassword)
                                .textFieldStyle(.plain)
                                .textContentType(.password)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .submitLabel(.go)
                                .onSubmit { emailAuth(isSignUp: false) }
                                .modifier(SandyField())

                            HStack(spacing: Theme.Spacing.sm) {
                                SandyButton(title: lang.lang == .ar ? "دخول" : "Sign in",
                                            systemImage: "arrow.right.circle.fill",
                                            isLoading: emailLoading,
                                            fillWidth: true) { emailAuth(isSignUp: false) }
                                SandyButton(title: lang.lang == .ar ? "حساب جديد" : "Sign up",
                                            style: .secondary,
                                            fillWidth: true) { emailAuth(isSignUp: true) }
                            }


                            if !error.isEmpty {
                                SandyNotice(error, kind: .gentleWarning)
                            }
                        }
                    }
                    .opacity(appeared ? 1 : 0)
                    .offset(y: appeared ? 0 : 16)
                }
                .padding(Theme.Spacing.lg)
                .frame(maxWidth: 460)
                .frame(maxWidth: .infinity)
            }
            .scrollBounceBehavior(.basedOnSize)
            .scrollDismissesKeyboard(.interactively)
        }
        .onAppear {
            guard !appeared else { return }
            if reduceMotion { appeared = true; return }
            withAnimation(.spring(response: 0.6, dampingFraction: 0.85).delay(0.05)) {
                appeared = true
            }
        }
    }

    /// خطّ شعري رفيع للفاصل.
    private var hairline: some View {
        Rectangle()
            .fill(Theme.Colors.border)
            .frame(height: 1)
    }

    /// فاصل نصّي بخطّين رفيعين حوله.
    private func dividerLabel(_ text: String) -> some View {
        HStack(spacing: Theme.Spacing.sm) {
            hairline
            Text(text)
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
                .fixedSize()
            hairline
        }
    }

    private func googleSignIn() {
        error = ""
        Task {
            do {
                let idToken = try await GoogleAuth.signIn()
                let done = try await state.api.signInGoogle(idToken: idToken)
                state.routeAfterAuth(onboardingDone: done)
            } catch {
                self.error = friendlyAuthError(error)
            }
        }
    }

    private func emailAuth(isSignUp: Bool) {
        let mail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !emailLoading, !mail.isEmpty, !emailPassword.isEmpty else { return }
        emailLoading = true; error = ""
        Task {
            do {
                let done = isSignUp
                    ? try await state.api.signUpEmail(email: mail, password: emailPassword)
                    : try await state.api.signInEmail(email: mail, password: emailPassword)
                state.routeAfterAuth(onboardingDone: done)
            } catch {
                self.error = friendlyAuthError(error)
            }
            emailLoading = false
        }
    }

    /// بتفرّع على `code` مش `message` لأن الرسالة نص عربي بيتغيّر.
    private func friendlyAuthError(_ error: Error) -> String {
        let ar = lang.lang == .ar
        let apiError = error as? APIError
        let msg = apiError?.message ?? error.localizedDescription
        switch apiError?.code ?? msg {
        case "email_taken":
            return ar ? "هالإيميل مستعمل — جرّب تسجّل دخول."
                      : "Email already in use — try signing in."
        case "invalid_credentials": return ar ? "الإيميل أو كلمة السر غلط." : "Wrong email or password."
        case "weak_password":
            return ar ? "كلمة السر لازم ثمن خانات على الأقل."
                      : "Password must be at least 8 characters."
        case "invalid_email":       return ar ? "الإيميل مش صحيح." : "Invalid email."
        case "auth_unavailable":    return ar ? "تعذّر الاتصال — جرّب بعد شوي." : "Service unavailable — try again."
        default:                    return msg
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
/// سطح داكن + حدّ خفيف؛ يُستعمل مع `.textFieldStyle(.plain)`.
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
