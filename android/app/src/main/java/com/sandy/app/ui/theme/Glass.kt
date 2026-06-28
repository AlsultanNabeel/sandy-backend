package com.sandy.app.ui.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp

/**
 * Sandy "liquid glass" surface — the Compose analog of iOS `LiquidGlass`
 * (Theme.swift). Real-time backdrop blur is API 31+ and costly, so on Android
 * we approximate the look with a translucent dark fill + a faint blue tint
 * gradient + a top-left shine border. Same identity, no behavior cost.
 */
fun Modifier.liquidGlass(
    corner: Dp = Radius.card,
    tint: Float = 0.06f,
    shine: Float = 0.24f,
): Modifier = this
    .clip(RoundedCornerShape(corner))
    .background(
        Brush.linearGradient(
            colors = listOf(
                SandyColors.card.copy(alpha = 0.82f),
                SandyColors.surface.copy(alpha = 0.74f),
            )
        )
    )
    .background(
        Brush.linearGradient(
            colors = listOf(
                SandyColors.accent.copy(alpha = tint),
                SandyColors.accent.copy(alpha = tint * 0.2f),
            )
        )
    )
    .border(
        width = androidx.compose.ui.unit.Dp.Hairline,
        brush = Brush.linearGradient(
            colors = listOf(
                Color.White.copy(alpha = shine),
                SandyColors.accent.copy(alpha = shine * 0.55f),
                Color.White.copy(alpha = shine * 0.1f),
            )
        ),
        shape = RoundedCornerShape(corner),
    )

/**
 * The screen background — obsidian with two soft blue radial glows, so the glass
 * surfaces have something to "break". Ports iOS `SandyBackground`. Use as the
 * root of every screen behind a Box.
 */
@Composable
fun SandyBackground(content: @Composable () -> Unit) {
    Box(
        Modifier
            .fillMaxSize()
            .background(SandyColors.background)
            .drawBehind {
                // Top-left glow.
                drawRect(
                    Brush.radialGradient(
                        colors = listOf(SandyColors.accent.copy(alpha = 0.10f), Color.Transparent),
                        center = Offset(0f, 0f),
                        radius = size.minDimension * 1.1f,
                    )
                )
                // Bottom-right glow.
                drawRect(
                    Brush.radialGradient(
                        colors = listOf(SandyColors.accentDeep.copy(alpha = 0.08f), Color.Transparent),
                        center = Offset(size.width, size.height),
                        radius = size.minDimension * 1.2f,
                    )
                )
            }
    ) {
        content()
    }
}

/** Convenience: a glass card with standard inner padding (ports `sandyCard`). */
fun Modifier.sandyCard(corner: Dp = Radius.card): Modifier =
    this.liquidGlass(corner).padding(Spacing.md)
