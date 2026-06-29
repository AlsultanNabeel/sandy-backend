package com.sandy.app.data

import com.sandy.app.i18n.Localization
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Talks to the Sandy backend — a Kotlin port of iOS `APIClient.swift`. Keeps the
 * same JSON-dict style (org.json mirrors Swift's [String: Any]) and the same
 * endpoints. The token is held by [tokenStore] so it persists and is sent as a
 * Bearer header on authed calls.
 */
class ApiClient(var baseURL: String, private val tokenStore: TokenStore) {

    val token: String? get() = tokenStore.token

    /** Core request. Throws [ApiException] on HTTP >= 400 (message from `error`). */
    private suspend fun request(
        path: String,
        method: String = "GET",
        body: JSONObject? = null,
        auth: Boolean = true,
    ): JSONObject = withContext(Dispatchers.IO) {
        val conn = (URL(baseURL + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 20_000
            readTimeout = 30_000
            setRequestProperty("Content-Type", "application/json")
            if (auth) tokenStore.token?.let { setRequestProperty("Authorization", "Bearer $it") }
            if (body != null) {
                doOutput = true
                outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
        }
        try {
            val code = conn.responseCode
            val stream = if (code >= 400) conn.errorStream else conn.inputStream
            val text = stream?.bufferedReader()?.use(BufferedReader::readText).orEmpty()
            val json = if (text.isBlank()) JSONObject() else runCatching { JSONObject(text) }.getOrDefault(JSONObject())
            if (code >= 400) throw ApiException(json.optString("error").ifEmpty { "خطأ $code" })
            json
        } finally {
            conn.disconnect()
        }
    }

    private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")

    // MARK: - Auth (token stored on success)

    private fun JSONObject.tokenOrThrow(msg: String): String =
        optString("token").ifEmpty { throw ApiException(msg) }

    suspend fun devLogin(password: String) {
        val r = request("/api/auth", "POST", JSONObject().put("password", password), auth = false)
        tokenStore.token = r.tokenOrThrow("ما رجع توكن")
    }

    suspend fun signInGoogle(idToken: String): Boolean {
        val r = request("/api/auth/google", "POST", JSONObject().put("id_token", idToken), auth = false)
        tokenStore.token = r.tokenOrThrow("فشل التحقّق من جوجل")
        return r.optBoolean("onboarding_done", false)
    }

    suspend fun signUpEmail(email: String, password: String): Boolean {
        val r = request(
            "/api/auth/email/register", "POST",
            JSONObject().put("email", email).put("password", password), auth = false,
        )
        tokenStore.token = r.tokenOrThrow("فشل إنشاء الحساب")
        return r.optBoolean("onboarding_done", false)
    }

    suspend fun signInEmail(email: String, password: String): Boolean {
        val r = request(
            "/api/auth/email/login", "POST",
            JSONObject().put("email", email).put("password", password), auth = false,
        )
        tokenStore.token = r.tokenOrThrow("بيانات الدخول غلط")
        return r.optBoolean("onboarding_done", false)
    }

    fun signOut() { tokenStore.token = null }

    // MARK: - Onboarding

    suspend fun getOnboarding(): OnboardingData {
        val r = request("/api/onboarding")
        return OnboardingData(
            done = r.optBoolean("done", false),
            preferredName = r.optString("preferred_name"),
            interests = r.optJSONArray("interests").toStringList(),
            name = r.optString("name"),
        )
    }

    suspend fun saveOnboarding(preferredName: String, interests: List<String>) {
        request(
            "/api/onboarding", "POST",
            JSONObject().put("preferred_name", preferredName).put("interests", JSONArray(interests)),
        )
    }

    // MARK: - Chat

    suspend fun sendMessage(text: String, conversationId: String? = null): String {
        val body = JSONObject().put("message", text).put("lang", Localization.lang)
        if (!conversationId.isNullOrEmpty()) body.put("conversation_id", conversationId)
        return request("/api/agent", "POST", body).optString("reply", "…")
    }

    // MARK: - Tasks

    suspend fun getTasks(completed: Boolean = false): ListResult<TaskItem> {
        val r = request(if (completed) "/api/tasks?completed=1" else "/api/tasks")
        val items = r.optJSONArray("items").objects().mapNotNull { row ->
            val id = row.optString("id").ifEmpty { return@mapNotNull null }
            TaskItem(
                id = id,
                text = row.optString("text"),
                done = row.optBoolean("done", false),
                dueAt = row.optString("due_at"),
                note = row.optString("note"),
                priority = row.optString("priority").ifEmpty { "normal" },
            )
        }
        return ListResult(items, r.optBoolean("demo", false))
    }

    suspend fun addTask(text: String, due: String = "", note: String? = null, priority: String? = null) {
        val body = JSONObject().put("text", text).put("due", due)
        note?.let { body.put("note", it) }
        priority?.let { body.put("priority", it) }
        request("/api/tasks", "POST", body)
    }

    suspend fun setTaskDone(id: String, done: Boolean) {
        request("/api/tasks/$id", "PATCH", JSONObject().put("done", done))
    }

    suspend fun deleteTask(id: String) { request("/api/tasks/$id", "DELETE") }

    // MARK: - Reminders

    suspend fun getReminders(): ListResult<ReminderItem> {
        val r = request("/api/reminders")
        val items = r.optJSONArray("items").objects().mapNotNull { row ->
            val id = row.optString("id").ifEmpty { return@mapNotNull null }
            ReminderItem(
                id = id,
                text = row.optString("text"),
                remindAt = row.optString("remind_at"),
                isRecurring = row.optBoolean("is_recurring", false),
                note = row.optString("note"),
            )
        }
        return ListResult(items, r.optBoolean("demo", false))
    }

    suspend fun addReminder(text: String, remindAt: String, note: String? = null) {
        val body = JSONObject().put("text", text).put("remind_at", remindAt)
        note?.let { body.put("note", it) }
        request("/api/reminders", "POST", body)
    }

    suspend fun deleteReminder(id: String) { request("/api/reminders/$id", "DELETE") }

    // MARK: - Habits

    suspend fun getHabits(): ListResult<HabitItem> {
        val r = request("/api/life/habits")
        val items = r.optJSONArray("items").objects().mapNotNull { row ->
            val id = row.optString("id").ifEmpty { return@mapNotNull null }
            HabitItem(
                id = id,
                name = row.optString("name"),
                streak = row.optInt("streak", 0),
                doneToday = row.optBoolean("done_today", false),
            )
        }
        return ListResult(items, r.optBoolean("demo", false))
    }

    suspend fun addHabit(name: String) {
        request("/api/life/habits", "POST", JSONObject().put("name", name))
    }

    suspend fun checkinHabit(name: String) {
        request("/api/life/habits/checkin", "POST", JSONObject().put("name", name))
    }

    suspend fun deleteHabit(id: String) { request("/api/life/habits/$id", "DELETE") }

    // MARK: - Expenses

    suspend fun getExpenses(): ExpensesResult {
        val r = request("/api/life/expenses")
        val items = r.optJSONArray("items").objects().mapNotNull { row ->
            val id = row.optString("id").ifEmpty { return@mapNotNull null }
            ExpenseItem(
                id = id,
                amount = row.optDouble("amount", 0.0),
                note = row.optString("note"),
                category = row.optString("category"),
                at = row.optString("at"),
            )
        }
        val s = r.optJSONObject("summary") ?: JSONObject()
        val summary = ExpensesSummary(total = s.optDouble("total", 0.0), count = s.optInt("count", 0))
        return ExpensesResult(items, summary, r.optBoolean("demo", false))
    }

    suspend fun addExpense(amount: Double, note: String, category: String) {
        request(
            "/api/life/expenses", "POST",
            JSONObject().put("amount", amount).put("note", note).put("category", category),
        )
    }

    /** Patch an expense; only non-null fields are sent. No-op if all are null. */
    suspend fun updateExpense(id: String, amount: Double? = null, note: String? = null, category: String? = null) {
        val body = JSONObject()
        amount?.let { body.put("amount", it) }
        note?.let { body.put("note", it) }
        category?.let { body.put("category", it) }
        if (body.length() == 0) return
        request("/api/life/expenses/$id", "PATCH", body)
    }

    suspend fun deleteExpense(id: String) { request("/api/life/expenses/$id", "DELETE") }

    // MARK: - Journal

    suspend fun getJournal(): ListResult<JournalEntry> {
        val r = request("/api/life/journal")
        val items = r.optJSONArray("items").objects().mapNotNull { row ->
            val id = row.optString("id").ifEmpty { return@mapNotNull null }
            JournalEntry(id = id, date = row.optString("date"), text = row.optString("text"))
        }
        return ListResult(items, r.optBoolean("demo", false))
    }

    suspend fun addJournalEntry(text: String) {
        request("/api/life/journal", "POST", JSONObject().put("text", text))
    }

    suspend fun updateJournalEntry(id: String, text: String) {
        request("/api/life/journal/$id", "PATCH", JSONObject().put("text", text))
    }

    suspend fun deleteJournalEntry(id: String) { request("/api/life/journal/$id", "DELETE") }

    // MARK: - Focus (Pomodoro)

    suspend fun getFocusStatus(): FocusStatus {
        val r = request("/api/life/focus")
        return FocusStatus(
            active = r.optBoolean("active", false),
            label = r.optString("label"),
            scene = r.optString("scene"),
            phase = r.optString("phase").ifEmpty { "focus" },
            cycleIdx = r.optInt("cycle_idx", 1),
            cycles = r.optInt("cycles", 1),
            focusMin = r.optInt("focus_min", 25),
            breakMin = r.optInt("break_min", 0),
            remainingSec = r.optInt("remaining_sec", 0),
            totalSec = r.optInt("total_sec", 0),
            demo = r.optBoolean("demo", false),
        )
    }

    suspend fun startFocus(
        focusMin: Int,
        breakMin: Int,
        cycles: Int,
        scene: String = "",
        endScene: String = "",
        label: String = "",
    ) {
        request(
            "/api/life/focus/start", "POST",
            JSONObject()
                .put("focus_min", focusMin).put("break_min", breakMin).put("cycles", cycles)
                .put("scene", scene).put("end_scene", endScene).put("label", label),
        )
    }

    suspend fun stopFocus(cancel: Boolean) {
        request("/api/life/focus/stop", "POST", JSONObject().put("cancel", cancel))
    }

    suspend fun getFocusHistory(limit: Int = 30): List<FocusSession> {
        val r = request("/api/life/focus/history?limit=$limit")
        return r.optJSONArray("sessions").objects().map { row ->
            FocusSession(
                label = row.optString("label"),
                minutes = row.optInt("minutes", 0),
                completed = row.optBoolean("completed", false),
                startedAt = row.optString("started_at"),
            )
        }
    }

    // MARK: - Conversations (chat history)

    suspend fun listConversations(): List<ConversationMeta> {
        val r = request("/api/conversations")
        return r.optJSONArray("items").objects().map { row ->
            ConversationMeta(
                id = row.optString("id"),
                title = row.optString("title"),
                updatedAt = row.optString("updated_at"),
            )
        }
    }

    suspend fun createConversation(): String {
        val r = request("/api/conversations", "POST", JSONObject())
        return r.optString("id").ifEmpty { throw ApiException("تعذّر إنشاء المحادثة") }
    }

    /** Returns the conversation title and its messages. */
    suspend fun getConversation(id: String): Pair<String, List<ChatMessage>> {
        val r = request("/api/conversations/$id")
        val msgs = r.optJSONArray("messages").objects().mapNotNull { m ->
            val role = m.optString("role").ifEmpty { return@mapNotNull null }
            val text = m.optString("text").ifEmpty { return@mapNotNull null }
            ChatMessage(role, text)
        }
        return r.optString("title") to msgs
    }

    suspend fun appendMessage(cid: String, role: String, text: String) {
        request(
            "/api/conversations/$cid/messages", "POST",
            JSONObject().put("role", role).put("text", text),
        )
    }

    suspend fun renameConversation(id: String, title: String) {
        request("/api/conversations/$id", "PATCH", JSONObject().put("title", title))
    }

    suspend fun deleteConversation(id: String) { request("/api/conversations/$id", "DELETE") }

    suspend fun searchConversations(q: String): List<ConversationHit> {
        val r = request("/api/conversations/search?q=${enc(q)}")
        return r.optJSONArray("items").objects().map { row ->
            ConversationHit(
                id = row.optString("id"),
                title = row.optString("title"),
                snippet = row.optString("snippet"),
                updatedAt = row.optString("updated_at"),
            )
        }
    }
}

// MARK: - small JSON helpers

private fun JSONArray?.objects(): List<JSONObject> {
    if (this == null) return emptyList()
    return (0 until length()).mapNotNull { optJSONObject(it) }
}

private fun JSONArray?.toStringList(): List<String> {
    if (this == null) return emptyList()
    return (0 until length()).map { optString(it) }
}
