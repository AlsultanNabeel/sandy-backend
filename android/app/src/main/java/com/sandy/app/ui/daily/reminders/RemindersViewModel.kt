package com.sandy.app.ui.daily.reminders

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sandy.app.data.ApiClient
import com.sandy.app.data.ReminderItem
import com.sandy.app.i18n.Localization
import kotlinx.coroutines.launch

/**
 * Reminders store — same store pattern as [com.sandy.app.ui.daily.tasks.TasksViewModel].
 * Loads from `/api/reminders`; add/delete mutate the backend then reload. `remind_at`
 * is required and the backend rejects past times, so the screen sends a future ISO.
 */
class RemindersViewModel(private val api: ApiClient) : ViewModel() {

    var reminders by mutableStateOf<List<ReminderItem>>(emptyList())
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
                val result = api.getReminders()
                reminders = result.items
                demo = result.demo
            } catch (e: Exception) {
                error = e.message ?: Localization.s("common.error")
            } finally {
                loading = false
            }
        }
    }

    /** [remindAt] is a local ISO string (`yyyy-MM-dd'T'HH:mm:ss`) for a future time. */
    fun add(text: String, remindAt: String) {
        val clean = text.trim()
        if (clean.isEmpty() || remindAt.isEmpty()) return
        viewModelScope.launch {
            runCatching { api.addReminder(text = clean, remindAt = remindAt) }
                .onSuccess { load() }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    fun delete(reminder: ReminderItem) {
        // Optimistic removal, then reconcile by reloading.
        reminders = reminders.filterNot { it.id == reminder.id }
        viewModelScope.launch {
            runCatching { api.deleteReminder(reminder.id) }
                .onSuccess { load() }
                .onFailure {
                    error = it.message ?: Localization.s("common.error")
                    load()
                }
        }
    }
}
