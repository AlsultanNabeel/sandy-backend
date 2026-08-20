import SwiftUI
import AuthenticationServices

/// شاشة الدخول — مبنيّة بالكامل على نظام تصميم ساندي (خلفية أوبسيديان + بطاقة
/// زجاجية + أزرار/تنبيهات ساندي) بدل أدوات النظام المصمتة. الهيكل بسيط ومتدفّق
/// داخل `ScrollView` فيتصرّف سليم بكل المقاسات ومع ظهور الكيبورد (ما في عناصر
/// تتداخل ولا Spacers تطفو بلا اتزان).
struct AuthView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @State private var error = ""
    // دخول/تسجيل بالإيميل.
    @State private var email = ""
    @State private var emailPassword = ""
    @State private var emailLoading = false

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

                    // بطاقة الدخول: أبل، جوجل، إيميل.
                    //
                    // حقل «عنوان الخادم» انشال. كان أداة تطوير — بتخلّيني أوجّه
                    // التطبيق ع خادم محلي — وضلّ ظاهر لكل مستخدم بأول شاشة.
                    //
                    // وهاد مش بس مش مرتّب. حرف واحد غلط فيه بيخلّي كل إشي يفشل
                    // بلا سبب ظاهر، **والأسوأ**: بيقدر يوجّه التطبيق كله — مع
                    // كلمات السرّ والصوت — ع خادم مش إلنا. حقل نصّ مفتوح بيقرّر
                    // ع مين بتنبعت بياناتك، وهو مكشوف قبل الدخول.
                    //
                    // العنوان محفوظ بـ`Backend` وبينقرا من هناك. أي تجريب محلي
                    // بيصير من متغيّر بالبناء، مش من شاشة الزبون.
                    SandyCard {
                        VStack(spacing: Theme.Spacing.md) {
                            SignInWithAppleButton(.signIn,
                                onRequest: { $0.requestedScopes = [.fullName, .email] },
                                onCompletion: handleApple)
                                .frame(height: 50)
                                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.control,
                                                            style: .continuous))
                                .signInWithAppleButtonStyle(.white)

                            // الدخول بجوجل.
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

                            // فاصل "أو بالإيميل".
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

                            // «دخول المطوّر» انحذف من هون.
                            //
                            // كان حقل كلمة سرّ بيدخّلك ع حساب اسمه «المالك» —
                            // حساب جاي من متغيّر بيئة، مش شخص. يعني أي حدا
                            // بيعرف الكلمة كان بيصير **نفس** الشخص: نفس
                            // اليوميات، ونفس المصاريف، ونفس بصمة الصوت.
                            //
                            // اشتغل لأنه كان في مستخدم واحد. وما بيتوسّع
                            // لتاني واحد بأي شكل.

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

    /// فاصل نصّي بخطّين رفيعين حوله (يُستعمل لـ "أو بالإيميل" / "أو دخول المطوّر").
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

    /// الدخول بجوجل — يفتح نافذة جوجل، ياخد id token، ويبعته للباك‑إند.
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

    /// دخول أو إنشاء حساب بالإيميل — نفس الحقول، يقرّرها `isSignUp`.
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

    /// يترجم رموز خطأ الباك‑إند لرسائل ودّية حسب اللغة.
    private func friendlyAuthError(_ error: Error) -> String {
        let ar = lang.lang == .ar
        let msg = (error as? APIError)?.message ?? error.localizedDescription
        switch msg {
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
