package com.sandy.app.ui.life.expenses

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sandy.app.data.ApiClient
import com.sandy.app.data.ExpenseItem
import com.sandy.app.data.ExpensesSummary
import com.sandy.app.i18n.Localization
import kotlinx.coroutines.launch

/**
 * Expenses store — Kotlin port of the iOS `ExpensesStore`. Single source of truth
 * for the expenses screen: loads from `/api/expenses`, and add/update/delete mutate
 * the backend then reload. Same store pattern as [com.sandy.app.ui.daily.tasks.TasksViewModel].
 */
class ExpensesViewModel(private val api: ApiClient) : ViewModel() {

    var items by mutableStateOf<List<ExpenseItem>>(emptyList())
        private set
    var summary by mutableStateOf(ExpensesSummary(total = 0.0, count = 0))
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
                val result = api.getExpenses()
                items = result.items
                summary = result.summary
                demo = result.demo
            } catch (e: Exception) {
                error = e.message ?: Localization.s("common.error")
            } finally {
                loading = false
            }
        }
    }

    fun add(amount: Double, note: String, category: String) {
        viewModelScope.launch {
            runCatching { api.addExpense(amount = amount, note = note.trim(), category = category.trim()) }
                .onSuccess { load() }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    fun update(item: ExpenseItem, amount: Double, note: String, category: String) {
        viewModelScope.launch {
            runCatching {
                api.updateExpense(item.id, amount = amount, note = note.trim(), category = category.trim())
            }
                .onSuccess { load() }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    fun delete(item: ExpenseItem) {
        // Optimistic removal, then reconcile by reloading.
        items = items.filterNot { it.id == item.id }
        viewModelScope.launch {
            runCatching { api.deleteExpense(item.id) }
                .onSuccess { load() }
                .onFailure {
                    error = it.message ?: Localization.s("common.error")
                    load()
                }
        }
    }
}
