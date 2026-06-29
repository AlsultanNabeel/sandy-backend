package com.sandy.app.data

/**
 * Domain models — port of the iOS `Models.swift` shapes the backend returns.
 * Only the models needed by the current foundation (auth, chat, daily, life)
 * live here; more are added as their features are built.
 */

/** Onboarding / profile data (GET /api/onboarding). */
data class OnboardingData(
    val done: Boolean = false,
    val preferredName: String = "",
    val interests: List<String> = emptyList(),
    val name: String = "",
)

/** A chat message (role = "user" | "assistant"). */
data class ChatMessage(val role: String, val text: String)

/** A conversation row in the chat history list (GET /api/conversations). */
data class ConversationMeta(
    val id: String,
    val title: String,
    val updatedAt: String,
)

/** A conversation search hit (GET /api/conversations/search). */
data class ConversationHit(
    val id: String,
    val title: String,
    val snippet: String,
    val updatedAt: String,
)

/** A task (GET /api/tasks items). */
data class TaskItem(
    val id: String,
    val text: String,
    val done: Boolean,
    val dueAt: String = "",
    val note: String = "",
    val priority: String = "normal",
)

/** A reminder (GET /api/reminders items). */
data class ReminderItem(
    val id: String,
    val text: String,
    val remindAt: String,
    val isRecurring: Boolean = false,
    val note: String = "",
)

/** A habit (GET /api/life/habits items). */
data class HabitItem(
    val id: String,
    val name: String,
    val streak: Int,
    val doneToday: Boolean,
)

/** An expense (GET /api/life/expenses items). */
data class ExpenseItem(
    val id: String,
    val amount: Double,
    val note: String,
    val category: String,
    val at: String,
)

/** A journal entry (GET /api/life/journal items). */
data class JournalEntry(
    val id: String,
    val date: String,
    val text: String,
)

/** Expenses summary (GET /api/life/expenses `summary`). */
data class ExpensesSummary(val total: Double = 0.0, val count: Int = 0)

/** Expenses result: items + summary + demo flag. */
data class ExpensesResult(
    val items: List<ExpenseItem>,
    val summary: ExpensesSummary,
    val demo: Boolean = false,
)

/** Focus (Pomodoro) session status (GET /api/life/focus). */
data class FocusStatus(
    val active: Boolean = false,
    val label: String = "",
    val scene: String = "",
    val phase: String = "focus", // "focus" | "break"
    val cycleIdx: Int = 1,
    val cycles: Int = 1,
    val focusMin: Int = 25,
    val breakMin: Int = 0,
    val remainingSec: Int = 0,
    val totalSec: Int = 0,
    val demo: Boolean = false,
) {
    val isBreak: Boolean get() = phase == "break"
}

/** A past focus session (GET /api/life/focus/history). */
data class FocusSession(
    val label: String,
    val minutes: Int,
    val completed: Boolean,
    val startedAt: String,
)

/** Generic list result that also carries the backend's `demo` flag. */
data class ListResult<T>(val items: List<T>, val demo: Boolean = false)

/** A backend/client error carrying a human message (mirrors iOS `APIError`). */
class ApiException(message: String) : Exception(message)
