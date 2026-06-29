package com.sandy.app.ui.daily

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.sandy.app.data.ApiClient
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.daily.focus.FocusScreen
import com.sandy.app.ui.daily.habits.HabitsScreen
import com.sandy.app.ui.daily.reminders.RemindersScreen
import com.sandy.app.ui.daily.tasks.TasksScreen
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing

/**
 * Daily tab — the planning hub. A segmented switch picks Tasks / Reminders /
 * Habits; each sub-screen owns its store and content. Focus and the rest join in
 * later sessions. The selected section survives recomposition/rotation.
 */
@Composable
fun DailyScreen(api: ApiClient) {
    var section by rememberSaveable { mutableStateOf(0) }

    Column(Modifier.fillMaxSize()) {
        Text(
            Localization.s("daily.title"),
            style = SandyType.largeTitle,
            color = SandyColors.primaryText,
            modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.md),
        )

        Row(
            modifier = Modifier.padding(horizontal = Spacing.lg),
            horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            SectionChip(0, section, "tasks.title") { section = 0 }
            SectionChip(1, section, "reminders.title") { section = 1 }
            SectionChip(2, section, "habits.title") { section = 2 }
            SectionChip(3, section, "focus.title") { section = 3 }
        }

        Box(Modifier.fillMaxWidth().weight(1f)) {
            when (section) {
                0 -> TasksScreen(api)
                1 -> RemindersScreen(api)
                2 -> HabitsScreen(api)
                else -> FocusScreen(api)
            }
        }
    }
}

@Composable
private fun SectionChip(index: Int, selected: Int, titleKey: String, onClick: () -> Unit) {
    FilterChip(
        selected = selected == index,
        onClick = onClick,
        label = { Text(Localization.s(titleKey)) },
    )
}
