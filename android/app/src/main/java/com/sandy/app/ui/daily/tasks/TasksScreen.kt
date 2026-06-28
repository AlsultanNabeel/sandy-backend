package com.sandy.app.ui.daily.tasks

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
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.outlined.Circle
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sandy.app.data.ApiClient
import com.sandy.app.data.TaskItem
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.components.SandyButton
import com.sandy.app.ui.components.SandyTextField
import com.sandy.app.ui.theme.IconSize
import com.sandy.app.ui.theme.Radius
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing
import com.sandy.app.ui.theme.sandyCard
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Tasks screen — port of the iOS `TasksView`. Active/completed filter, add with
 * an optional due date, tap to complete, delete. Drives [TasksViewModel].
 */
@Composable
fun TasksScreen(api: ApiClient) {
    val vm: TasksViewModel = viewModel { TasksViewModel(api) }

    Column(Modifier.fillMaxSize().padding(horizontal = Spacing.lg)) {
        Text(
            Localization.s("tasks.title"),
            style = SandyType.largeTitle,
            color = SandyColors.primaryText,
            modifier = Modifier.padding(top = Spacing.lg, bottom = Spacing.md),
        )

        // Active / completed filter.
        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            FilterChip(
                selected = !vm.showCompleted,
                onClick = { vm.setShowCompleted(false) },
                label = { Text(Localization.s("tasks.active")) },
            )
            FilterChip(
                selected = vm.showCompleted,
                onClick = { vm.setShowCompleted(true) },
                label = { Text(Localization.s("tasks.completed")) },
            )
        }

        AddTaskRow(onAdd = vm::add)

        vm.error?.let {
            Text(
                it,
                style = SandyType.subheadline,
                color = SandyColors.danger,
                modifier = Modifier.padding(vertical = Spacing.sm),
            )
        }

        Box(Modifier.fillMaxSize()) {
            if (vm.tasks.isEmpty() && !vm.loading) {
                Text(
                    Localization.s("tasks.empty"),
                    style = SandyType.subheadline,
                    color = SandyColors.secondaryText,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            LazyColumn(
                contentPadding = PaddingValues(top = Spacing.md, bottom = 100.dp),
                verticalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                items(vm.tasks, key = { it.id }) { task ->
                    TaskRow(
                        task = task,
                        onToggle = { vm.toggleDone(task) },
                        onDelete = { vm.delete(task) },
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddTaskRow(onAdd: (text: String, due: String) -> Unit) {
    var text by remember { mutableStateOf("") }
    var dueMillis by remember { mutableStateOf<Long?>(null) }
    var showPicker by remember { mutableStateOf(false) }

    Row(
        modifier = Modifier.fillMaxWidth().padding(top = Spacing.md),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        Box(Modifier.weight(1f)) {
            SandyTextField(text, { text = it }, Localization.s("tasks.addPlaceholder"))
        }
        IconButton(onClick = { showPicker = true }) {
            Icon(
                Icons.Filled.CalendarMonth,
                contentDescription = Localization.s("tasks.pickDate"),
                tint = if (dueMillis != null) SandyColors.accent else SandyColors.secondaryText,
            )
        }
    }
    SandyButton(
        title = Localization.s("common.add"),
        onClick = {
            onAdd(text, dueMillis?.let { isoFromMillis(it) } ?: "")
            text = ""
            dueMillis = null
        },
        modifier = Modifier.padding(top = Spacing.sm),
        enabled = text.isNotBlank(),
    )

    if (showPicker) {
        val state = rememberDatePickerState(initialSelectedDateMillis = dueMillis)
        DatePickerDialog(
            onDismissRequest = { showPicker = false },
            confirmButton = {
                TextButton(onClick = { dueMillis = state.selectedDateMillis; showPicker = false }) {
                    Text(Localization.s("common.save"))
                }
            },
            dismissButton = {
                TextButton(onClick = { showPicker = false }) {
                    Text(Localization.s("common.cancel"))
                }
            },
        ) {
            DatePicker(state = state)
        }
    }
}

@Composable
private fun TaskRow(task: TaskItem, onToggle: () -> Unit, onDelete: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().sandyCard(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        IconButton(onClick = onToggle) {
            Icon(
                if (task.done) Icons.Filled.CheckCircle else Icons.Outlined.Circle,
                contentDescription = null,
                tint = if (task.done) SandyColors.success else SandyColors.secondaryText,
            )
        }
        Column(Modifier.weight(1f)) {
            Text(
                task.text,
                style = SandyType.body,
                color = if (task.done) SandyColors.tertiaryText else SandyColors.primaryText,
                textDecoration = if (task.done) TextDecoration.LineThrough else TextDecoration.None,
            )
            val due = displayDue(task.dueAt)
            if (due != null) {
                Text(due, style = SandyType.caption, color = SandyColors.secondaryText)
            }
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

// MARK: - date helpers

private val isoOut = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss")

/** A picked day (UTC midnight millis) → local ISO at 09:00, like the iOS sheet. */
private fun isoFromMillis(millis: Long): String {
    val date = Instant.ofEpochMilli(millis).atZone(ZoneId.of("UTC")).toLocalDate()
    return date.atTime(9, 0).format(isoOut)
}

/** Show just the date part of an ISO/`yyyy-MM-dd` string, or null if empty. */
private fun displayDue(raw: String): String? {
    if (raw.isBlank()) return null
    return if (raw.length >= 10) raw.substring(0, 10) else raw
}
