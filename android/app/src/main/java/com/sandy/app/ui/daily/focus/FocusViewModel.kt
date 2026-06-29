package com.sandy.app.ui.daily.focus

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sandy.app.data.ApiClient
import com.sandy.app.data.FocusSession
import com.sandy.app.data.FocusStatus
import com.sandy.app.i18n.Localization
import kotlinx.coroutines.launch

/**
 * Focus store — Kotlin port of the iOS Pomodoro timer (`FocusView`). Single
 * source of truth for the focus screen: loads the live timer status and the past
 * sessions, and start/stop mutate the backend then reload. Follows the store
 * pattern every feature follows.
 *
 * Created per-screen via `viewModel { FocusViewModel(api) }`, so it gets a
 * `viewModelScope` and survives recomposition/rotation.
 */
class FocusViewModel(private val api: ApiClient) : ViewModel() {

    var status by mutableStateOf(FocusStatus())
        private set
    var history by mutableStateOf<List<FocusSession>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var demo by mutableStateOf(false)
        private set

    init { load() }

    fun load() {
        loading = true
        error = null
        viewModelScope.launch {
            try {
                val live = api.getFocusStatus()
                status = live
                demo = live.demo
                history = api.getFocusHistory()
            } catch (e: Exception) {
                error = e.message ?: Localization.s("common.error")
            } finally {
                loading = false
            }
        }
    }

    fun start(focusMin: Int, breakMin: Int, cycles: Int, label: String) {
        viewModelScope.launch {
            runCatching { api.startFocus(focusMin, breakMin, cycles, label = label.trim()) }
                .onSuccess { load() }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    fun stop(cancel: Boolean) {
        viewModelScope.launch {
            runCatching { api.stopFocus(cancel) }
                .onSuccess { load() }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }
}
