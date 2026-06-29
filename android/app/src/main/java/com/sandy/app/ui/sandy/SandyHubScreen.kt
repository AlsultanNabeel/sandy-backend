package com.sandy.app.ui.sandy

import androidx.compose.runtime.Composable
import com.sandy.app.data.ApiClient
import com.sandy.app.ui.sandy.chat.ChatScreen

/**
 * Sandy tab — the unified intelligence hub. For now the tab *is* the chat with
 * Sandy plus conversation history; Search and Images are later sessions and will
 * mount here alongside chat.
 */
@Composable
fun SandyHubScreen(api: ApiClient) = ChatScreen(api)
