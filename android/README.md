# Sandy — Android app

Native Android client (Kotlin + Jetpack Compose) for the same Sandy backend the
iOS app and web use. One backend, many frontends.

## Status: foundation
The shell is built first (same approach as iOS), then features are mounted into
their tabs one by one.

Done:
- Project + Gradle (version catalog), dark Material3 theme.
- Design system ported from iOS `Theme.swift` — `SandyColors`, `Spacing`,
  `Radius`, `IconSize`, `SandyType`, `liquidGlass`/`SandyBackground` (glass look
  approximated without runtime blur).
- Networking: `ApiClient` (Kotlin port of `APIClient.swift`, same endpoints) +
  `TokenStore` (encrypted, the Keychain analog) so the session persists.
- `SessionViewModel` (the `AppState` analog): launch → restore → auth /
  onboarding / main.
- Email + password sign-in/up against the backend.
- The Core-4 shell: floating glass tab bar (الرئيسية / ساندي / يومي / حياتي).
- In-app i18n (ar/en) mirroring the iOS `Localization` system.

Next (per feature, into their tabs):
- Daily: tasks, reminders, habits, focus.
- Life: journal, expenses.
- Sandy: chat, search, images.
- Home: dashboard snapshot + quick-add.
- Google sign-in (Credential Manager), local notifications, widgets.

## Build
Open the `android/` folder in Android Studio (Giraffe+ / latest) and let it sync.
It targets `compileSdk 35`, `minSdk 26`. The backend base URL is in
`SessionViewModel.DEFAULT_BASE_URL`.

The Gradle wrapper jar is not committed; Android Studio provisions Gradle 8.9
(pinned in `gradle/wrapper/gradle-wrapper.properties`) on first sync. For a CLI
build, run `gradle wrapper` once, then `./gradlew assembleDebug`.

## Layout
```
android/
  app/src/main/
    AndroidManifest.xml
    java/com/sandy/app/
      MainActivity.kt
      data/      ApiClient, Models, TokenStore
      i18n/      Localization (ar/en table)
      ui/
        theme/      Color, Dimens, Type, Theme, Glass
        components/  SandyButton, SandyTextField, TabPlaceholder
        auth/        AuthScreen
        onboarding/  OnboardingScreen
        shell/       MainScaffold + floating tab bar
        home/ sandy/ daily/ life/   tab screens
        SessionViewModel, SandyApp
    res/values/  themes.xml, strings.xml
```
