package com.sandy.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.sandy.app.ui.theme.Radius
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing

/**
 * Primary call-to-action — a pill with the electric-blue gradient. Ports the
 * iOS `SandyButton` primary style. Use one dominant CTA per screen.
 */
@Composable
fun SandyButton(
    title: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    loading: Boolean = false,
) {
    val active = enabled && !loading
    val interaction = remember { MutableInteractionSource() }
    Box(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = 52.dp)
            .clip(RoundedCornerShape(Radius.control))
            .background(
                Brush.linearGradient(listOf(SandyColors.accent, SandyColors.accentDeep))
            )
            .alpha(if (active) 1f else 0.5f)
            .then(
                if (active) Modifier.clickable(
                    interactionSource = interaction, indication = null, onClick = onClick,
                ) else Modifier
            )
            .padding(vertical = Spacing.md),
        contentAlignment = Alignment.Center,
    ) {
        if (loading) {
            CircularProgressIndicator(color = SandyColors.onAccent, strokeWidth = 2.dp)
        } else {
            Text(title, style = SandyType.button, color = SandyColors.onAccent)
        }
    }
}

/** A text field styled for the dark glass surfaces. */
@Composable
fun SandyTextField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    isPassword: Boolean = false,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.fillMaxWidth(),
        singleLine = true,
        placeholder = { Text(placeholder, color = SandyColors.tertiaryText) },
        visualTransformation =
            if (isPassword) PasswordVisualTransformation() else VisualTransformation.None,
        shape = RoundedCornerShape(Radius.control),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = SandyColors.accent,
            unfocusedBorderColor = SandyColors.border,
            focusedTextColor = SandyColors.primaryText,
            unfocusedTextColor = SandyColors.primaryText,
            cursorColor = SandyColors.accent,
            focusedContainerColor = SandyColors.surface.copy(alpha = 0.5f),
            unfocusedContainerColor = SandyColors.surface.copy(alpha = 0.5f),
        ),
    )
}
