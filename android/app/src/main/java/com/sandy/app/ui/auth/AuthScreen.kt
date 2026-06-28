package com.sandy.app.ui.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import com.sandy.app.ui.components.SandyTextField
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing
import kotlinx.coroutines.launch

/**
 * Sign-in / sign-up by email + password — ports the email part of iOS `AuthView`.
 * Hits the backend (`/api/auth/email/...`) and routes via the session. Google /
 * Apple sign-in are added in a later pass (need the Credential Manager wiring).
 */
@Composable
fun AuthScreen(session: SessionViewModel) {
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    fun authenticate(isSignUp: Boolean) {
        if (email.isBlank() || password.isBlank() || loading) return
        loading = true
        error = null
        scope.launch {
            try {
                val done =
                    if (isSignUp) session.api.signUpEmail(email.trim(), password)
                    else session.api.signInEmail(email.trim(), password)
                session.routeAfterAuth(done)
            } catch (e: Exception) {
                error = e.message ?: Localization.s("auth.error.generic")
            } finally {
                loading = false
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(Spacing.lg),
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

        val fieldMod = Modifier.widthIn(max = 420.dp)
        SandyTextField(email, { email = it }, Localization.s("auth.email"), fieldMod)
        Spacer(Modifier.height(Spacing.md))
        SandyTextField(password, { password = it }, Localization.s("auth.password"), fieldMod, isPassword = true)

        error?.let {
            Spacer(Modifier.height(Spacing.md))
            Text(it, style = SandyType.subheadline, color = SandyColors.danger, textAlign = TextAlign.Center)
        }

        Spacer(Modifier.height(Spacing.lg))
        SandyButton(
            title = Localization.s("auth.login"),
            onClick = { authenticate(isSignUp = false) },
            modifier = fieldMod,
            loading = loading,
        )
        Spacer(Modifier.height(Spacing.sm))
        TextButton(onClick = { authenticate(isSignUp = true) }, enabled = !loading) {
            Text(Localization.s("auth.signup"), color = SandyColors.accent)
        }
    }
}
