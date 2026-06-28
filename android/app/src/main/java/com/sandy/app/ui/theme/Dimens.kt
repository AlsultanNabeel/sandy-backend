package com.sandy.app.ui.theme

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** Spacing scale — ports iOS `Theme.Spacing`. Never use free numbers in screens. */
object Spacing {
    val xs: Dp = 4.dp
    val sm: Dp = 8.dp
    val md: Dp = 14.dp
    val lg: Dp = 20.dp
    val xl: Dp = 28.dp
    val xxl: Dp = 40.dp
    val section: Dp = 24.dp   // breathing room between screen sections
}

/** Corner radii — ports iOS `Theme.Radius`. */
object Radius {
    val card: Dp = 16.dp
    val bubble: Dp = 18.dp
    val control: Dp = 12.dp
    val pill: Dp = 999.dp
}

/** Unified icon sizes — ports iOS `Theme.Icon`. */
object IconSize {
    val sm: Dp = 15.dp   // inside buttons/labels
    val md: Dp = 18.dp   // row/toolbar icons
    val lg: Dp = 24.dp   // prominent icons
    val xl: Dp = 40.dp   // empty-state / hero
}
