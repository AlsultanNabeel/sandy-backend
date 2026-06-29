package com.sandy.app.ui.life.journal

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sandy.app.data.ApiClient
import com.sandy.app.data.JournalEntry
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.components.SandyButton
import com.sandy.app.ui.components.SandyTextField
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing
import com.sandy.app.ui.theme.sandyCard

/**
 * Journal screen — port of the iOS `JournalView`. Renders under the Life hub, so
 * it owns NO large title: it starts with the add row, then the list (date + text).
 * Add / delete are the must-haves; tapping a row loads it back into the add row
 * for an in-place edit via `updateJournalEntry`. Drives [JournalViewModel].
 */
@Composable
fun JournalScreen(api: ApiClient) {
    val vm: JournalViewModel = viewModel { JournalViewModel(api) }
    var editing by remember { mutableStateOf<JournalEntry?>(null) }

    Column(Modifier.fillMaxSize()) {
        AddJournalRow(
            editing = editing,
            onSubmit = { text ->
                val current = editing
                if (current != null) vm.update(current, text) else vm.add(text)
                editing = null
            },
            onCancelEdit = { editing = null },
        )

        vm.error?.let {
            Text(
                it,
                style = SandyType.subheadline,
                color = SandyColors.danger,
                modifier = Modifier.padding(vertical = Spacing.sm),
            )
        }

        Box(Modifier.fillMaxSize()) {
            if (vm.entries.isEmpty() && !vm.loading) {
                Text(
                    Localization.s("journal.empty"),
                    style = SandyType.subheadline,
                    color = SandyColors.secondaryText,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            LazyColumn(
                contentPadding = PaddingValues(top = Spacing.md, bottom = 100.dp),
                verticalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                items(vm.entries, key = { it.id }) { entry ->
                    JournalRow(
                        entry = entry,
                        onTap = { editing = entry },
                        onDelete = { vm.delete(entry) },
                    )
                }
            }
        }
    }
}

@Composable
private fun AddJournalRow(
    editing: JournalEntry?,
    onSubmit: (text: String) -> Unit,
    onCancelEdit: () -> Unit,
) {
    var text by remember(editing) { mutableStateOf(editing?.text ?: "") }

    Column(
        modifier = Modifier.fillMaxWidth().padding(top = Spacing.md),
        verticalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        SandyTextField(text, { text = it }, Localization.s("journal.placeholder"))

        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            Box(Modifier.weight(1f)) {
                SandyButton(
                    title = Localization.s(if (editing != null) "common.save" else "common.add"),
                    onClick = {
                        onSubmit(text)
                        text = ""
                    },
                    enabled = text.isNotBlank(),
                )
            }
            if (editing != null) {
                Box(Modifier.weight(1f)) {
                    SandyButton(
                        title = Localization.s("common.cancel"),
                        onClick = onCancelEdit,
                    )
                }
            }
        }
    }
}

@Composable
private fun JournalRow(entry: JournalEntry, onTap: () -> Unit, onDelete: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onTap).sandyCard(),
        verticalAlignment = Alignment.Top,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(Spacing.xs),
        ) {
            if (entry.date.isNotEmpty()) {
                Text(entry.date, style = SandyType.caption, color = SandyColors.tertiaryText)
            }
            Text(entry.text, style = SandyType.body, color = SandyColors.primaryText)
        }
        IconButton(onClick = onDelete) {
            Icon(
                Icons.Filled.Delete,
                contentDescription = Localization.s("common.delete"),
                tint = SandyColors.danger,
            )
        }
    }
}
