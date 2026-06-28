package com.sandy.app.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.runtime.CompositionLocalProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.auth.AuthScreen
import com.sandy.app.ui.onboarding.OnboardingScreen
import com.sandy.app.ui.shell.MainScaffold
import com.sandy.app.ui.theme.SandyBackground
import com.sandy.app.ui.theme.SandyColors

/**
 * Root composable — restores the session on launch and shows the stage's screen
 * (launching → auth → onboarding → main). Ports iOS `RootView`. Lays everything
 * over the Sandy background and honors the chosen language's direction (RTL/LTR).
 */
@Composable
fun SandyApp() {
    val session: SessionViewModel = viewModel()

    LaunchedEffect(Unit) { session.restoreSession() }

    val direction = if (Localization.isRtl) LayoutDirection.Rtl else LayoutDirection.Ltr
    CompositionLocalProvider(LocalLayoutDirection provides direction) {
        SandyBackground {
            when (session.stage) {
                SessionViewModel.Stage.Launching ->
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = SandyColors.accent)
                    }
                SessionViewModel.Stage.Auth -> AuthScreen(session)
                SessionViewModel.Stage.Onboarding -> OnboardingScreen(session)
                SessionViewModel.Stage.Chat -> MainScaffold(session)
            }
        }
    }
}
