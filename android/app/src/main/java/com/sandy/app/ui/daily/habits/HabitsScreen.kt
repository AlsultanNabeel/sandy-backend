package com.sandy.app.ui.daily.habits

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.LocalFireDepartment
import androidx.compose.material.icons.outlined.Circle
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
import com.sandy.app.data.HabitItem
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.components.SandyButton
import com.sandy.app.ui.components.SandyTextField
import com.sandy.app.ui.theme.IconSize
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing
import com.sandy.app.ui.theme.sandyCard

/**
 * Habits screen — port of the iOS `HabitsView` (trimmed to list/add/checkin/delete).
 * Tap the circle to check in for today; the row shows the running streak. Drives
 * [HabitsViewModel].
 */
@Composable
fun HabitsScreen(api: ApiClient) {
    val vm: HabitsViewModel = viewModel { HabitsViewModel(api) }

    Column(Modifier.fillMaxSize().padding(horizontal = Spacing.lg)) {
        AddHabitRow(onAdd = vm::add)

        vm.error?.let {
            Text(
                it,
                style = SandyType.subheadline,
                color = SandyColors.danger,
                modifier = Modifier.padding(vertical = Spacing.sm),
            )
        }

        Box(Modifier.fillMaxSize()) {
            if (vm.habits.isEmpty() && !vm.loading) {
                Text(
                    Localization.s("habits.empty"),
                    style = SandyType.subheadline,
                    color = SandyColors.secondaryText,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            LazyColumn(
                contentPadding = PaddingValues(top = Spacing.md, bottom = 100.dp),
                verticalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                items(vm.habits, key = { it.id }) { habit ->
                    HabitRow(
                        habit = habit,
                        onCheckin = { vm.checkin(habit) },
                        onDelete = { vm.delete(habit) },
                    )
                }
            }
        }
    }
}

@Composable
private fun AddHabitRow(onAdd: (name: String) -> Unit) {
    var name by remember { mutableStateOf("") }

    Column(Modifier.padding(top = Spacing.md)) {
        SandyTextField(name, { name = it }, Localization.s("habits.addPlaceholder"))
        SandyButton(
            title = Localization.s("common.add"),
            onClick = {
                onAdd(name)
                name = ""
            },
            modifier = Modifier.padding(top = Spacing.sm),
            enabled = name.isNotBlank(),
        )
    }
}

@Composable
private fun HabitRow(habit: HabitItem, onCheckin: () -> Unit, onDelete: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().sandyCard(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        IconButton(onClick = onCheckin, enabled = !habit.doneToday) {
            Icon(
                if (habit.doneToday) Icons.Filled.CheckCircle else Icons.Outlined.Circle,
                contentDescription = Localization.s("habits.doneToday"),
                tint = if (habit.doneToday) SandyColors.success else SandyColors.secondaryText,
            )
        }
        Column(Modifier.weight(1f)) {
            Text(habit.name, style = SandyType.body, color = SandyColors.primaryText)
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Spacing.xs),
            ) {
                if (habit.streak > 0) {
                    Icon(
                        Icons.Filled.LocalFireDepartment,
                        contentDescription = null,
                        tint = SandyColors.accentDeep,
                        modifier = Modifier.size(IconSize.sm),
                    )
                    Text(
                        String.format(Localization.s("habits.streak"), habit.streak),
                        style = SandyType.caption,
                        color = SandyColors.accentDeep,
                    )
                } else {
                    Text(
                        Localization.s("habits.noStreak"),
                        style = SandyType.caption,
                        color = SandyColors.secondaryText,
                    )
                }
                if (habit.doneToday) {
                    Text(
                        "• " + Localization.s("habits.doneToday"),
                        style = SandyType.caption,
                        color = SandyColors.success,
                    )
                }
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
