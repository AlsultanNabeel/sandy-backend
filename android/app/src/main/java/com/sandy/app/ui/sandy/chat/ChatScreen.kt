package com.sandy.app.ui.sandy.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.History
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SheetState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sandy.app.data.ApiClient
import com.sandy.app.data.ChatMessage
import com.sandy.app.data.ConversationMeta
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.components.SandyTextField
import com.sandy.app.ui.theme.IconSize
import com.sandy.app.ui.theme.Radius
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing
import com.sandy.app.ui.theme.sandyCard

/**
 * Chat screen — port of the iOS `ChatView`. A scrolling list of message bubbles
 * (your turns right-aligned in an accent bubble, Sandy's left in a glass card), a
 * bottom input row, a "thinking" indicator while a reply is in flight, and an
 * empty state. The top bar exposes history: a "new conversation" action and a
 * sheet listing saved conversations (open / rename / delete + search).
 *
 * Drives [ChatViewModel], the chat store.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(api: ApiClient) {
    val vm: ChatViewModel = viewModel { ChatViewModel(api) }
    var showHistory by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().padding(horizontal = Spacing.lg)) {
        // Title row with history + new-conversation actions.
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = Spacing.lg, bottom = Spacing.md),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = { showHistory = true }) {
                Icon(
                    Icons.Filled.History,
                    contentDescription = Localization.s("chat.history"),
                    tint = SandyColors.accent,
                )
            }
            Text(
                Localization.s("chat.title"),
                style = SandyType.title,
                color = SandyColors.primaryText,
                modifier = Modifier.weight(1f).padding(horizontal = Spacing.sm),
            )
            IconButton(onClick = { vm.newConversation() }) {
                Icon(
                    Icons.Filled.Add,
                    contentDescription = Localization.s("chat.newConversation"),
                    tint = SandyColors.accent,
                )
            }
        }

        vm.error?.let {
            Text(
                it,
                style = SandyType.subheadline,
                color = SandyColors.danger,
                modifier = Modifier.padding(bottom = Spacing.sm),
            )
        }

        // Message list (fills the remaining height above the input row).
        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (vm.messages.isEmpty() && !vm.sending) {
                Text(
                    Localization.s("chat.empty"),
                    style = SandyType.subheadline,
                    color = SandyColors.secondaryText,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(vertical = Spacing.md),
                verticalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                items(vm.messages) { message ->
                    MessageBubble(message)
                }
                if (vm.sending) {
                    item { ThinkingIndicator() }
                }
            }
        }

        InputRow(
            value = vm.input,
            onValueChange = { vm.input = it },
            onSend = { vm.send(vm.input) },
            sending = vm.sending,
        )
    }

    if (showHistory) {
        HistorySheet(
            vm = vm,
            sheetState = rememberModalBottomSheetState(),
            onDismiss = { showHistory = false },
        )
    }
}

/** Cap bubbles so long lines wrap instead of spanning the full width. */
private val BubbleMaxWidth = 320.dp

/** Bound the history list inside the bottom sheet (a LazyColumn needs a max height). */
private val HistoryListMaxHeight = 420.dp

@Composable
private fun MessageBubble(message: ChatMessage) {
    val isUser = message.role == "user"
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        if (isUser) {
            Text(
                message.text,
                style = SandyType.body,
                color = SandyColors.primaryText,
                modifier = Modifier
                    .widthIn(max = BubbleMaxWidth)
                    .clip(RoundedCornerShape(Radius.bubble))
                    .background(SandyColors.userBubble)
                    .padding(Spacing.md),
            )
        } else {
            Text(
                message.text,
                style = SandyType.body,
                color = SandyColors.primaryText,
                modifier = Modifier
                    .widthIn(max = BubbleMaxWidth)
                    .sandyCard(corner = Radius.bubble),
            )
        }
    }
}

/** "Sandy is thinking…" placeholder shown in a glass card while a reply loads. */
@Composable
private fun ThinkingIndicator() {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
        Row(
            modifier = Modifier.sandyCard(corner = Radius.bubble),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            CircularProgressIndicator(
                color = SandyColors.accent,
                strokeWidth = 2.dp,
                modifier = Modifier.size(IconSize.md),
            )
            Text(
                Localization.s("chat.thinking"),
                style = SandyType.subheadline,
                color = SandyColors.secondaryText,
            )
        }
    }
}

@Composable
private fun InputRow(
    value: String,
    onValueChange: (String) -> Unit,
    onSend: () -> Unit,
    sending: Boolean,
) {
    val canSend = value.isNotBlank() && !sending
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = Spacing.md),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        Box(Modifier.weight(1f)) {
            SandyTextField(value, onValueChange, Localization.s("chat.placeholder"))
        }
        IconButton(onClick = onSend, enabled = canSend) {
            Icon(
                Icons.AutoMirrored.Filled.Send,
                contentDescription = Localization.s("chat.send"),
                tint = if (canSend) SandyColors.accent else SandyColors.tertiaryText,
            )
        }
    }
}

/** History sheet — saved conversations with search, open, rename, and delete. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun HistorySheet(
    vm: ChatViewModel,
    sheetState: SheetState,
    onDismiss: () -> Unit,
) {
    var query by remember { mutableStateOf("") }
    var renameTarget by remember { mutableStateOf<ConversationMeta?>(null) }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = SandyColors.card,
    ) {
        Column(Modifier.fillMaxWidth().padding(horizontal = Spacing.lg, vertical = Spacing.md)) {
            Text(
                Localization.s("chat.history"),
                style = SandyType.title,
                color = SandyColors.primaryText,
                modifier = Modifier.padding(bottom = Spacing.md),
            )
            Box(Modifier.padding(bottom = Spacing.md)) {
                SandyTextField(
                    value = query,
                    onValueChange = { query = it; vm.search(it) },
                    placeholder = Localization.s("chat.search"),
                )
            }

            val rows = if (query.isBlank()) {
                vm.conversations
            } else {
                // Map search hits back to the meta shape the row renders.
                vm.searchResults.map { ConversationMeta(it.id, it.title, it.updatedAt) }
            }

            if (rows.isEmpty()) {
                Text(
                    Localization.s("chat.empty"),
                    style = SandyType.subheadline,
                    color = SandyColors.secondaryText,
                    modifier = Modifier.padding(vertical = Spacing.lg),
                )
            } else {
                LazyColumn(
                    modifier = Modifier.heightIn(max = HistoryListMaxHeight),
                    contentPadding = PaddingValues(bottom = Spacing.xl),
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm),
                ) {
                    items(rows) { conv ->
                        ConversationRow(
                            conv = conv,
                            onOpen = { vm.openConversation(conv.id); onDismiss() },
                            onRename = { renameTarget = conv },
                            onDelete = { vm.delete(conv.id) },
                        )
                    }
                }
            }
        }
    }

    renameTarget?.let { target ->
        RenameDialog(
            initial = target.title,
            onConfirm = { vm.rename(target.id, it); renameTarget = null },
            onDismiss = { renameTarget = null },
        )
    }
}

@Composable
private fun ConversationRow(
    conv: ConversationMeta,
    onOpen: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(Radius.card))
            .clickable(onClick = onOpen)
            .sandyCard(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        Text(
            conv.title.ifBlank { Localization.s("chat.untitled") },
            style = SandyType.body,
            color = SandyColors.primaryText,
            modifier = Modifier.weight(1f),
        )
        IconButton(onClick = onRename) {
            Icon(
                Icons.Filled.Edit,
                contentDescription = Localization.s("chat.rename"),
                tint = SandyColors.secondaryText,
            )
        }
        IconButton(onClick = onDelete) {
            Icon(
                Icons.Filled.Delete,
                contentDescription = Localization.s("chat.delete"),
                tint = SandyColors.danger,
            )
        }
    }
}

@Composable
private fun RenameDialog(
    initial: String,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var text by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = SandyColors.card,
        title = { Text(Localization.s("chat.rename"), color = SandyColors.primaryText) },
        text = {
            SandyTextField(text, { text = it }, Localization.s("chat.rename"))
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(text) }) {
                Text(Localization.s("common.save"), color = SandyColors.accent)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(Localization.s("common.cancel"), color = SandyColors.secondaryText)
            }
        },
    )
}
