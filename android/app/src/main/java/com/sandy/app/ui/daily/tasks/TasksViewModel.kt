package com.sandy.app.ui.daily.tasks

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sandy.app.data.ApiClient
import com.sandy.app.data.TaskItem
import com.sandy.app.i18n.Localization
import kotlinx.coroutines.launch

/**
 * Tasks store — Kotlin port of the iOS `TasksStore`. Single source of truth for
 * the tasks screen: loads from `/api/tasks`, and add/toggle/delete mutate the
 * backend then reload. This is the store pattern every feature follows.
 *
 * Created per-screen via `viewModel { TasksViewModel(api) }`, so it gets a
 * `viewModelScope` and survives recomposition/rotation.
 */
class TasksViewModel(private val api: ApiClient) : ViewModel() {

    var tasks by mutableStateOf<List<TaskItem>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var showCompleted by mutableStateOf(false)
        private set
    var demo by mutableStateOf(false)
        private set

    init { load() }

    fun load() {
        loading = true
        error = null
        viewModelScope.launch {
            try {
                val result = api.getTasks(completed = showCompleted)
                tasks = result.items
                demo = result.demo
            } catch (e: Exception) {
                error = e.message ?: Localization.s("common.error")
            } finally {
                loading = false
            }
        }
    }

    fun filterCompleted(value: Boolean) {
        if (value == showCompleted) return
        showCompleted = value
        load()
    }

    fun add(text: String, due: String = "") {
        val clean = text.trim()
        if (clean.isEmpty()) return
        viewModelScope.launch {
            runCatching { api.addTask(text = clean, due = due) }
                .onSuccess { load() }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    fun toggleDone(task: TaskItem) {
        viewModelScope.launch {
            runCatching { api.setTaskDone(task.id, !task.done) }
                .onSuccess { load() }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    fun delete(task: TaskItem) {
        // Optimistic removal, then reconcile by reloading.
        tasks = tasks.filterNot { it.id == task.id }
        viewModelScope.launch {
            runCatching { api.deleteTask(task.id) }
                .onSuccess { load() }
                .onFailure {
                    error = it.message ?: Localization.s("common.error")
                    load()
                }
        }
    }
}
