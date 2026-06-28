package com.sandy.app.ui.onboarding

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.SessionViewModel
import com.sandy.app.ui.components.SandyButton
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing
import kotlinx.coroutines.launch

/**
 * Minimal first-run welcome — marks onboarding done on the backend, then enters
 * the app. The richer interest/name flow (iOS `OnboardingView`) is ported later.
 */
@Composable
fun OnboardingScreen(session: SessionViewModel) {
    var loading by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Column(
        modifier = Modifier.fillMaxSize().padding(Spacing.lg),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            Localization.s("auth.welcome"),
            style = SandyType.largeTitle,
            color = SandyColors.primaryText,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(Spacing.sm))
        Text(
            Localization.s("auth.subtitle"),
            style = SandyType.subheadline,
            color = SandyColors.secondaryText,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(Spacing.xl))
        SandyButton(
            title = Localization.s("auth.login"),
            onClick = {
                if (loading) return@SandyButton
                loading = true
                scope.launch {
                    runCatching {
                        session.api.saveOnboarding(session.onboarding.name, emptyList())
                    }
                    session.completeOnboarding()
                }
            },
            modifier = Modifier.widthIn(max = 420.dp),
            loading = loading,
        )
    }
}
