package com.sandy.app.ui.shell

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Home
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.SessionViewModel
import com.sandy.app.ui.daily.DailyScreen
import com.sandy.app.ui.home.HomeScreen
import com.sandy.app.ui.life.LifeScreen
import com.sandy.app.ui.sandy.SandyHubScreen
import com.sandy.app.ui.theme.Radius
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing
import com.sandy.app.ui.theme.liquidGlass

/** The four Core-4 tabs — mirrors iOS `MainTab`. */
enum class MainTab(val icon: ImageVector, val titleKey: String) {
    Home(Icons.Filled.Home, "tabs.home"),
    Sandy(Icons.Filled.AutoAwesome, "tabs.sandy"),
    Daily(Icons.Filled.CalendarMonth, "tabs.daily"),
    Life(Icons.Filled.Favorite, "tabs.life"),
}

/**
 * The post-login shell — content area + a floating glass tab bar at the bottom.
 * Ports iOS `MainTabView` / `FloatingTabBar`. The selected tab expands into a
 * blue pill with its label; the rest stay quiet icons.
 */
@Composable
fun MainScaffold(session: SessionViewModel) {
    var selection by remember { mutableStateOf(MainTab.Home) }

    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().padding(bottom = 84.dp)) {
            when (selection) {
                MainTab.Home -> HomeScreen()
                MainTab.Sandy -> SandyHubScreen(session.api)
                MainTab.Daily -> DailyScreen(session.api)
                MainTab.Life -> LifeScreen(session.api)
            }
        }
        FloatingTabBar(
            selection = selection,
            onSelect = { selection = it },
            modifier = Modifier.align(Alignment.BottomCenter),
        )
    }
}

@Composable
private fun FloatingTabBar(
    selection: MainTab,
    onSelect: (MainTab) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .padding(horizontal = Spacing.lg, vertical = Spacing.sm)
            .fillMaxWidth()
            .liquidGlass(corner = Radius.pill, tint = 0.08f)
            .padding(6.dp),
        horizontalArrangement = Arrangement.spacedBy(Spacing.xs),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MainTab.entries.forEach { tab ->
            TabButton(
                tab = tab,
                selected = selection == tab,
                onClick = { onSelect(tab) },
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun TabButton(
    tab: MainTab,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val interaction = remember { MutableInteractionSource() }
    val tint = if (selected) SandyColors.onAccent else SandyColors.secondaryText
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(Radius.pill))
            .then(
                if (selected) Modifier.background(
                    Brush.linearGradient(listOf(SandyColors.accent, SandyColors.accentDeep))
                ) else Modifier
            )
            .clickable(interactionSource = interaction, indication = null, onClick = onClick)
            .padding(horizontal = if (selected) Spacing.md else Spacing.sm, vertical = 10.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(tab.icon, contentDescription = Localization.s(tab.titleKey), tint = tint)
        if (selected) {
            Text(
                "  " + Localization.s(tab.titleKey),
                style = SandyType.callout,
                color = tint,
                maxLines = 1,
            )
        }
    }
}
