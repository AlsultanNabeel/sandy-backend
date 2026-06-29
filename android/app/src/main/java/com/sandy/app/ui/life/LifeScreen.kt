package com.sandy.app.ui.life

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
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.sandy.app.data.ApiClient
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.life.expenses.ExpensesScreen
import com.sandy.app.ui.life.journal.JournalScreen
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing

/** The sections of the Life hub — meaning & memories. */
private enum class LifeSection(val titleKey: String) {
    Expenses("life.expenses"),
    Journal("life.journal"),
}

/**
 * Life tab — a hub over Expenses and Journal, mirroring the Daily/Tasks hub shape.
 * The hub owns the large title and the section chips; each sub-screen renders no
 * title of its own and starts with its add row.
 */
@Composable
fun LifeScreen(api: ApiClient) {
    var section by remember { mutableStateOf(LifeSection.Expenses) }

    Column(Modifier.fillMaxSize().padding(horizontal = Spacing.lg)) {
        Text(
            Localization.s("life.title"),
            style = SandyType.largeTitle,
            color = SandyColors.primaryText,
            modifier = Modifier.padding(top = Spacing.lg, bottom = Spacing.md),
        )

        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            LifeSection.entries.forEach { entry ->
                FilterChip(
                    selected = section == entry,
                    onClick = { section = entry },
                    label = { Text(Localization.s(entry.titleKey)) },
                )
            }
        }

        Box(Modifier.fillMaxWidth().weight(1f)) {
            when (section) {
                LifeSection.Expenses -> ExpensesScreen(api)
                LifeSection.Journal -> JournalScreen(api)
            }
        }
    }
}
