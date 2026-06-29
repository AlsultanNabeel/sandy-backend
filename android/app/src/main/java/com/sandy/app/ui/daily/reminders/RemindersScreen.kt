package com.sandy.app.ui.daily.reminders

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
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
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
import com.sandy.app.data.ReminderItem
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.components.SandyButton
import com.sandy.app.ui.components.SandyTextField
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing
import com.sandy.app.ui.theme.sandyCard
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Reminders screen — port of the iOS `RemindersView` (trimmed to list/add/delete).
 * Add takes text + a future date & time (the backend requires `remind_at` and
 * rejects past times). Drives [RemindersViewModel].
 */
@Composable
fun RemindersScreen(api: ApiClient) {
    val vm: RemindersViewModel = viewModel { RemindersViewModel(api) }

    Column(Modifier.fillMaxSize().padding(horizontal = Spacing.lg)) {
        AddReminderRow(onAdd = vm::add)

        vm.error?.let {
            Text(
                it,
                style = SandyType.subheadline,
                color = SandyColors.danger,
                modifier = Modifier.padding(vertical = Spacing.sm),
            )
        }

        Box(Modifier.fillMaxSize()) {
            if (vm.reminders.isEmpty() && !vm.loading) {
                Text(
                    Localization.s("reminders.empty"),
                    style = SandyType.subheadline,
                    color = SandyColors.secondaryText,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            LazyColumn(
                contentPadding = PaddingValues(top = Spacing.md, bottom = 100.dp),
                verticalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                items(vm.reminders, key = { it.id }) { reminder ->
                    ReminderRow(reminder = reminder, onDelete = { vm.delete(reminder) })
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddReminderRow(onAdd: (text: String, remindAt: String) -> Unit) {
    var text by remember { mutableStateOf("") }
    // Default to a few minutes out so the first reminder isn't already in the past.
    var date by remember { mutableStateOf(LocalDate.now()) }
    var time by remember { mutableStateOf(LocalTime.now().plusMinutes(5).withSecond(0).withNano(0)) }
    var showDate by remember { mutableStateOf(false) }
    var showTime by remember { mutableStateOf(false) }

    Column(Modifier.padding(top = Spacing.md)) {
        SandyTextField(text, { text = it }, Localization.s("reminders.addPlaceholder"))

        Row(
            modifier = Modifier.fillMaxWidth().padding(top = Spacing.sm),
            horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            AssistChip(
                onClick = { showDate = true },
                label = { Text(date.format(dateLabel)) },
                leadingIcon = {
                    Icon(Icons.Filled.CalendarMonth, null, tint = SandyColors.accent)
                },
                colors = AssistChipDefaults.assistChipColors(labelColor = SandyColors.primaryText),
            )
            AssistChip(
                onClick = { showTime = true },
                label = { Text(time.format(timeLabel)) },
                leadingIcon = {
                    Icon(Icons.Filled.Schedule, null, tint = SandyColors.accent)
                },
                colors = AssistChipDefaults.assistChipColors(labelColor = SandyColors.primaryText),
            )
        }

        SandyButton(
            title = Localization.s("common.add"),
            onClick = {
                onAdd(text, LocalDateTime.of(date, time).format(isoOut))
                text = ""
            },
            modifier = Modifier.padding(top = Spacing.sm),
            enabled = text.isNotBlank(),
        )
    }

    if (showDate) {
        val state = rememberDatePickerState(
            initialSelectedDateMillis = date.atStartOfDay(ZoneId.of("UTC")).toInstant().toEpochMilli(),
        )
        DatePickerDialog(
            onDismissRequest = { showDate = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { date = localDateFromUtcMillis(it) }
                    showDate = false
                }) { Text(Localization.s("common.save")) }
            },
            dismissButton = {
                TextButton(onClick = { showDate = false }) { Text(Localization.s("common.cancel")) }
            },
        ) {
            DatePicker(state = state)
        }
    }

    if (showTime) {
        val state = rememberTimePickerState(initialHour = time.hour, initialMinute = time.minute)
        AlertDialog(
            onDismissRequest = { showTime = false },
            confirmButton = {
                TextButton(onClick = {
                    time = LocalTime.of(state.hour, state.minute)
                    showTime = false
                }) { Text(Localization.s("common.save")) }
            },
            dismissButton = {
                TextButton(onClick = { showTime = false }) { Text(Localization.s("common.cancel")) }
            },
            text = { TimePicker(state = state) },
        )
    }
}

@Composable
private fun ReminderRow(reminder: ReminderItem, onDelete: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().sandyCard(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        Icon(
            if (reminder.isRecurring) Icons.Filled.Repeat else Icons.Filled.Notifications,
            contentDescription = null,
            tint = SandyColors.accent,
        )
        Column(Modifier.weight(1f)) {
            Text(reminder.text, style = SandyType.body, color = SandyColors.primaryText)
            if (reminder.note.isNotBlank()) {
                Text(reminder.note, style = SandyType.caption, color = SandyColors.secondaryText)
            }
            val whenLabel = displayWhen(reminder.remindAt)
            if (whenLabel != null) {
                val suffix =
                    if (reminder.isRecurring) " • " + Localization.s("reminders.recurring") else ""
                Text(whenLabel + suffix, style = SandyType.caption, color = SandyColors.accentDeep)
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
private val dateLabel = DateTimeFormatter.ofPattern("EEE, d MMM")
private val timeLabel = DateTimeFormatter.ofPattern("HH:mm")
private val whenDisplay = DateTimeFormatter.ofPattern("EEE d MMM • HH:mm")

/** A picked day (UTC midnight millis from the date picker) → local date. */
private fun localDateFromUtcMillis(millis: Long): LocalDate =
    Instant.ofEpochMilli(millis).atZone(ZoneId.of("UTC")).toLocalDate()

/** Show a friendly date+time for a stored `remind_at`, or null if unparseable. */
private fun displayWhen(raw: String): String? {
    if (raw.isBlank()) return null
    val trimmed = raw.removeSuffix("Z").substringBefore('+')
    return runCatching { LocalDateTime.parse(trimmed).format(whenDisplay) }
        .getOrElse { if (raw.length >= 10) raw.substring(0, 10) else raw }
}
