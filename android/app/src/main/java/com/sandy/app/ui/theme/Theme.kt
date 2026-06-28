package com.sandy.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

/**
 * SandyTheme — wraps the app in a dark Material3 scheme keyed to our palette.
 * Screens mostly use [SandyColors] / [SandyType] directly (like iOS pulls from
 * Theme.*), but Material components (text fields, etc.) read this scheme.
 *
 * The app is dark-only by design (obsidian identity), matching iOS.
 */
private val SandyDarkScheme = darkColorScheme(
    primary = SandyColors.accent,
    onPrimary = SandyColors.onAccent,
    secondary = SandyColors.secondary,
    background = SandyColors.background,
    onBackground = SandyColors.primaryText,
    surface = SandyColors.surface,
    onSurface = SandyColors.primaryText,
    error = SandyColors.danger,
)

private val SandyTypography = Typography(
    titleLarge = SandyType.title,
    headlineSmall = SandyType.headline,
    bodyLarge = SandyType.body,
    bodyMedium = SandyType.subheadline,
    labelLarge = SandyType.button,
)

@Composable
fun SandyTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = SandyDarkScheme,
        typography = SandyTypography,
        content = content,
    )
}
