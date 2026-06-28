package com.sandy.app.ui

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.sandy.app.data.ApiClient
import com.sandy.app.data.OnboardingData
import com.sandy.app.data.TokenStore
import kotlinx.coroutines.launch

/**
 * App-wide session state — Kotlin port of iOS `AppState.swift`. Owns the single
 * [ApiClient] and drives which top-level screen shows via [stage]. On launch it
 * tries to restore a saved session (token in the encrypted store) before
 * deciding between auth / onboarding / main.
 */
class SessionViewModel(app: Application) : AndroidViewModel(app) {

    enum class Stage { Launching, Auth, Onboarding, Chat }

    private val tokenStore = TokenStore(app)
    val api = ApiClient(DEFAULT_BASE_URL, tokenStore)

    var stage by mutableStateOf(Stage.Launching)
        private set
    var onboarding by mutableStateOf(OnboardingData())
        private set

    /** Restore on launch: validate a saved token and route; else go to auth. */
    fun restoreSession() {
        viewModelScope.launch {
            if (api.token == null) { stage = Stage.Auth; return@launch }
            try {
                onboarding = api.getOnboarding()
                stage = if (onboarding.done) Stage.Chat else Stage.Onboarding
            } catch (_: Exception) {
                api.signOut()              // invalid/expired token → fail closed
                stage = Stage.Auth
            }
        }
    }

    /** After a successful sign-in: onboarding (first time) or main. */
    fun routeAfterAuth(onboardingDone: Boolean) {
        stage = if (onboardingDone) Stage.Chat else Stage.Onboarding
    }

    fun completeOnboarding() { stage = Stage.Chat }

    fun signOut() {
        api.signOut()
        onboarding = OnboardingData()
        stage = Stage.Auth
    }

    companion object {
        const val DEFAULT_BASE_URL = "https://sandy-robot-3da0693d32f7.herokuapp.com"
    }
}
