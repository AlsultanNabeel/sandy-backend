package com.sandy.app.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing

/**
 * A tab's first-pass screen: shows its title and a "coming soon" line. Each tab
 * gets its real content as that feature is ported (shell-first, like iOS).
 */
@Composable
fun TabPlaceholder(titleKey: String) {
    Column(
        modifier = Modifier.fillMaxSize().padding(Spacing.lg),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(Localization.s(titleKey), style = SandyType.largeTitle, color = SandyColors.primaryText)
        Spacer(Modifier.height(Spacing.sm))
        Text(
            Localization.s("common.comingSoon"),
            style = SandyType.subheadline,
            color = SandyColors.secondaryText,
            textAlign = TextAlign.Center,
        )
    }
}
