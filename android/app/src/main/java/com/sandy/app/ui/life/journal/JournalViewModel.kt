package com.sandy.app.ui.life.journal

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sandy.app.data.ApiClient
import com.sandy.app.data.JournalEntry
import com.sandy.app.i18n.Localization
import kotlinx.coroutines.launch

/**
 * Journal store — Kotlin port of the iOS `JournalStore`. Single source of truth
 * for the journal screen: loads from `/api/journal`, and add/update/delete mutate
 * the backend then reload. Same store pattern as
 * [com.sandy.app.ui.daily.tasks.TasksViewModel].
 */
class JournalViewModel(private val api: ApiClient) : ViewModel() {

    var entries by mutableStateOf<List<JournalEntry>>(emptyList())
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
                val result = api.getJournal()
                entries = result.items
                demo = result.demo
            } catch (e: Exception) {
                error = e.message ?: Localization.s("common.error")
            } finally {
                loading = false
            }
        }
    }

    fun add(text: String) {
        val clean = text.trim()
        if (clean.isEmpty()) return
        viewModelScope.launch {
            runCatching { api.addJournalEntry(clean) }
                .onSuccess { load() }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    fun update(entry: JournalEntry, text: String) {
        val clean = text.trim()
        if (clean.isEmpty()) return
        viewModelScope.launch {
            runCatching { api.updateJournalEntry(entry.id, clean) }
                .onSuccess { load() }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    fun delete(entry: JournalEntry) {
        // Optimistic removal, then reconcile by reloading.
        entries = entries.filterNot { it.id == entry.id }
        viewModelScope.launch {
            runCatching { api.deleteJournalEntry(entry.id) }
                .onSuccess { load() }
                .onFailure {
                    error = it.message ?: Localization.s("common.error")
                    load()
                }
        }
    }
}
