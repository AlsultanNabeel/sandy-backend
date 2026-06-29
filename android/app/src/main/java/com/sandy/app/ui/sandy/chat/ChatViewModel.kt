package com.sandy.app.ui.sandy.chat

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sandy.app.data.ApiClient
import com.sandy.app.data.ChatMessage
import com.sandy.app.data.ConversationHit
import com.sandy.app.data.ConversationMeta
import com.sandy.app.i18n.Localization
import kotlinx.coroutines.launch

/**
 * Chat store — Kotlin port of the iOS `ChatStore` (ChatView.swift). Single source
 * of truth for the Sandy chat: holds the current conversation's messages plus the
 * saved-conversation history, and persists every exchange to the conversations API.
 *
 * Follows the store pattern (mirrors [com.sandy.app.ui.daily.tasks.TasksViewModel]):
 * created per-screen via `viewModel { ChatViewModel(api) }`, so it gets a
 * `viewModelScope` and survives recomposition/rotation — switching tabs keeps the
 * conversation alive.
 *
 * A `null` [conversationId] means a "lazy" new conversation: it is only created on
 * the backend when the first message is sent, so we never leave empty conversations.
 */
class ChatViewModel(private val api: ApiClient) : ViewModel() {

    var messages by mutableStateOf<List<ChatMessage>>(emptyList())
        private set
    var conversationId by mutableStateOf<String?>(null)
        private set
    var conversations by mutableStateOf<List<ConversationMeta>>(emptyList())
        private set
    var input by mutableStateOf("")
    var sending by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    /** Live search results for the history sheet; empty when not searching. */
    var searchResults by mutableStateOf<List<ConversationHit>>(emptyList())
        private set

    init { loadConversations() }

    /** Refresh the saved-conversation list (history). */
    fun loadConversations() {
        viewModelScope.launch {
            runCatching { api.listConversations() }
                .onSuccess { conversations = it }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    /**
     * Send the trimmed input as a user turn. Appends the user message locally,
     * calls the brain, then appends Sandy's reply. Persists both turns via the
     * conversations API, lazily creating a conversation on the first message
     * (mirrors the iOS `ChatStore.send`).
     */
    fun send(text: String) {
        val clean = text.trim()
        if (clean.isEmpty() || sending) return

        messages = messages + ChatMessage(role = "user", text = clean)
        input = ""
        sending = true
        error = null

        viewModelScope.launch {
            runCatching {
                // Lazily create the conversation on the first message.
                val cid = conversationId ?: api.createConversation().also { conversationId = it }
                api.appendMessage(cid, "user", clean)
                val reply = api.sendMessage(clean, cid)
                messages = messages + ChatMessage(role = "assistant", text = reply)
                api.appendMessage(cid, "assistant", reply)
            }.onSuccess {
                loadConversations()
            }.onFailure {
                error = it.message ?: Localization.s("common.error")
            }
            sending = false
        }
    }

    /** Open a saved conversation: pull its messages and make it current. */
    fun openConversation(id: String) {
        viewModelScope.launch {
            runCatching { api.getConversation(id) }
                .onSuccess { (_, msgs) ->
                    messages = msgs
                    conversationId = id
                    error = null
                }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }

    /** Start a fresh (lazy) conversation: clear the view; create on first send. */
    fun newConversation() {
        messages = emptyList()
        conversationId = null
        error = null
    }

    /** Rename a saved conversation (optimistic), then reconcile with the server. */
    fun rename(id: String, title: String) {
        val clean = title.trim()
        if (clean.isEmpty()) return
        conversations = conversations.map { if (it.id == id) it.copy(title = clean) else it }
        viewModelScope.launch {
            runCatching { api.renameConversation(id, clean) }
                .onSuccess { loadConversations() }
                .onFailure {
                    error = it.message ?: Localization.s("common.error")
                    loadConversations()
                }
        }
    }

    /** Delete a saved conversation; if it was the open one, start fresh. */
    fun delete(id: String) {
        conversations = conversations.filterNot { it.id == id }
        if (id == conversationId) newConversation()
        viewModelScope.launch {
            runCatching { api.deleteConversation(id) }
                .onSuccess { loadConversations() }
                .onFailure {
                    error = it.message ?: Localization.s("common.error")
                    loadConversations()
                }
        }
    }

    /** Full-text search across saved conversations; blank query clears results. */
    fun search(q: String) {
        val clean = q.trim()
        if (clean.isEmpty()) {
            searchResults = emptyList()
            return
        }
        viewModelScope.launch {
            runCatching { api.searchConversations(clean) }
                .onSuccess { searchResults = it }
                .onFailure { error = it.message ?: Localization.s("common.error") }
        }
    }
}
