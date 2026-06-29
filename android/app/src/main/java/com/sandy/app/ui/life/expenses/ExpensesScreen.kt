package com.sandy.app.ui.life.expenses

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
import com.sandy.app.data.ExpenseItem
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.components.SandyButton
import com.sandy.app.ui.components.SandyTextField
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing
import com.sandy.app.ui.theme.sandyCard

/**
 * Expenses screen — port of the iOS `ExpensesView`. Renders under the Life hub,
 * so it owns NO large title: it starts with the add row, then a summary header
 * (total + count), then the list. Add / delete are the must-haves; tapping a row
 * loads it back into the add row for an in-place edit via `updateExpense`.
 * Drives [ExpensesViewModel].
 */
@Composable
fun ExpensesScreen(api: ApiClient) {
    val vm: ExpensesViewModel = viewModel { ExpensesViewModel(api) }
    var editing by remember { mutableStateOf<ExpenseItem?>(null) }

    Column(Modifier.fillMaxSize()) {
        AddExpenseRow(
            editing = editing,
            onSubmit = { amount, note, category ->
                val current = editing
                if (current != null) {
                    vm.update(current, amount, note, category)
                } else {
                    vm.add(amount, note, category)
                }
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

        SummaryHeader(total = vm.summary.total, count = vm.summary.count)

        Box(Modifier.fillMaxSize()) {
            if (vm.items.isEmpty() && !vm.loading) {
                Text(
                    Localization.s("expenses.empty"),
                    style = SandyType.subheadline,
                    color = SandyColors.secondaryText,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            LazyColumn(
                contentPadding = PaddingValues(top = Spacing.md, bottom = 100.dp),
                verticalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                items(vm.items, key = { it.id }) { item ->
                    ExpenseRow(
                        item = item,
                        onTap = { editing = item },
                        onDelete = { vm.delete(item) },
                    )
                }
            }
        }
    }
}

@Composable
private fun AddExpenseRow(
    editing: ExpenseItem?,
    onSubmit: (amount: Double, note: String, category: String) -> Unit,
    onCancelEdit: () -> Unit,
) {
    var amount by remember(editing) { mutableStateOf(editing?.amount?.let { formatAmount(it) } ?: "") }
    var note by remember(editing) { mutableStateOf(editing?.note ?: "") }
    var category by remember(editing) { mutableStateOf(editing?.category ?: "") }

    Column(
        modifier = Modifier.fillMaxWidth().padding(top = Spacing.md),
        verticalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        SandyTextField(
            value = amount,
            onValueChange = { amount = it.filter { c -> c.isDigit() || c == '.' } },
            placeholder = Localization.s("expenses.amount"),
        )
        SandyTextField(note, { note = it }, Localization.s("expenses.note"))
        SandyTextField(category, { category = it }, Localization.s("expenses.category"))

        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            Box(Modifier.weight(1f)) {
                SandyButton(
                    title = Localization.s(if (editing != null) "common.save" else "common.add"),
                    onClick = {
                        val value = amount.toDoubleOrNull() ?: return@SandyButton
                        onSubmit(value, note, category)
                        amount = ""
                        note = ""
                        category = ""
                    },
                    enabled = amount.toDoubleOrNull() != null,
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
private fun SummaryHeader(total: Double, count: Int) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = Spacing.md).sandyCard(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.md),
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                Localization.s("expenses.total"),
                style = SandyType.caption,
                color = SandyColors.secondaryText,
            )
            Text(
                formatAmount(total),
                style = SandyType.largeTitle,
                color = SandyColors.accentDeep,
            )
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                count.toString(),
                style = SandyType.title,
                color = SandyColors.accent,
            )
            Text(
                Localization.s("expenses.count"),
                style = SandyType.caption,
                color = SandyColors.tertiaryText,
            )
        }
    }
}

@Composable
private fun ExpenseRow(item: ExpenseItem, onTap: () -> Unit, onDelete: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onTap).sandyCard(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(Spacing.xs),
        ) {
            Text(
                title(item),
                style = SandyType.headline,
                color = SandyColors.primaryText,
            )
            if (item.category.isNotEmpty() && item.note.isNotEmpty()) {
                Text(item.category, style = SandyType.caption, color = SandyColors.tertiaryText)
            }
        }
        Text(
            formatAmount(item.amount),
            style = SandyType.headline,
            color = SandyColors.primaryText,
        )
        IconButton(onClick = onDelete) {
            Icon(
                Icons.Filled.Delete,
                contentDescription = Localization.s("common.delete"),
                tint = SandyColors.danger,
                modifier = Modifier.padding(start = Spacing.xs),
            )
        }
    }
}

/** The row title: note if present, else category, else a generic fallback. */
private fun title(item: ExpenseItem): String = when {
    item.note.isNotEmpty() -> item.note
    item.category.isNotEmpty() -> item.category
    else -> Localization.s("expenses.title")
}

/** Whole-number amounts drop the decimals; otherwise keep two places. */
private fun formatAmount(value: Double): String =
    if (value % 1.0 == 0.0) value.toLong().toString() else String.format("%.2f", value)
