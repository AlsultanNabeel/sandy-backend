package com.sandy.app.ui.daily.habits

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sandy.app.data.ApiClient
import com.sandy.app.data.HabitItem
import com.sandy.app.i18n.Localization
import kotlinx.coroutines.launch

/**
 * Habits store — same store pattern as the other daily features. Loads from
 * `/api/life/habits`; add/check-in/delete mutate the backend then reload. The
 * backend keys check-in by habit name (not id), mirroring the iOS store.
 */
class HabitsViewModel(private val api: ApiClient) : ViewModel() {

    var habits by mutableStateOf<List<HabitItem>>(emptyList())
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
                val result = api.getHabits()
                habits = result.items
                demo = result.demo
            } catch (e: Exception) {
                error = e.message ?: Localization.s("common.error")
            } finally {
                loading = false
            }
        }
    }

    fun add(name: String) {
        val clean = name.trim()
        if (clean.isEmpty()) return
        viewModelScope.launch {
            runCatching { api.addHabit(clean) }
                .onSuccess { load() }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    fun checkin(habit: HabitItem) {
        if (habit.doneToday) return
        viewModelScope.launch {
            runCatching { api.checkinHabit(habit.name) }
                .onSuccess { load() }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    fun delete(habit: HabitItem) {
        // Optimistic removal, then reconcile by reloading.
        habits = habits.filterNot { it.id == habit.id }
        viewModelScope.launch {
            runCatching { api.deleteHabit(habit.id) }
                .onSuccess { load() }
                .onFailure {
                    error = it.message ?: Localization.s("common.error")
                    load()
                }
        }
    }
}
