package com.sandy.app.ui.daily.focus

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.StopCircle
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sandy.app.data.ApiClient
import com.sandy.app.data.FocusSession
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.components.SandyButton
import com.sandy.app.ui.components.SandyTextField
import com.sandy.app.ui.theme.IconSize
import com.sandy.app.ui.theme.SandyColors
import com.sandy.app.ui.theme.SandyType
import com.sandy.app.ui.theme.Spacing
import com.sandy.app.ui.theme.sandyCard
import kotlinx.coroutines.delay
import java.util.Locale

/**
 * Focus screen — port of the iOS Pomodoro `FocusView`. When a session is running
 * it shows a big mm:ss countdown, the phase (focus/break), cycle progress and
 * Stop/Cancel. Otherwise it shows a setup form (focus/break minutes, cycles,
 * optional label) and Start, with the past sessions listed below. Drives
 * [FocusViewModel].
 */
@Composable
fun FocusScreen(api: ApiClient) {
    val vm: FocusViewModel = viewModel { FocusViewModel(api) }

    Column(Modifier.fillMaxSize().padding(horizontal = Spacing.lg)) {
        vm.error?.let {
            Text(
                it,
                style = SandyType.subheadline,
                color = SandyColors.danger,
                modifier = Modifier.padding(vertical = Spacing.sm),
            )
        }

        if (vm.status.active) {
            RunningCard(vm = vm)
        } else {
            SetupCard(onStart = vm::start)
            HistoryList(history = vm.history, loading = vm.loading)
        }
    }
}

// ── Running session: local countdown + phase + cycle + stop/cancel ──────────

@Composable
private fun RunningCard(vm: FocusViewModel) {
    val status = vm.status

    // Smooth local countdown: tick a local copy of remainingSec every second and
    // resync with the server when it hits zero or roughly every 15s.
    var remaining by remember(status.remainingSec) { mutableIntStateOf(status.remainingSec) }
    LaunchedEffect(status.active, status.remainingSec) {
        var ticks = 0
        while (status.active && remaining > 0) {
            delay(1_000)
            remaining -= 1
            ticks += 1
            if (remaining <= 0 || ticks >= 15) {
                vm.load() // phase likely ended, or periodic resync
                break
            }
        }
    }

    Column(
        modifier = Modifier.fillMaxWidth().padding(top = Spacing.lg).sandyCard(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Spacing.md),
    ) {
        Text(
            clock(remaining),
            style = SandyType.largeTitle,
            color = SandyColors.primaryText,
        )
        Text(
            if (status.isBreak) Localization.s("focus.phase.break")
            else Localization.s("focus.phase.focus"),
            style = SandyType.callout,
            color = if (status.isBreak) SandyColors.warn else SandyColors.accent,
        )
        if (status.label.isNotEmpty()) {
            Text(status.label, style = SandyType.headline, color = SandyColors.primaryText)
        }
        Text(
            String.format(
                Locale.getDefault(),
                Localization.s("focus.cycleOf"),
                status.cycleIdx,
                status.cycles,
            ),
            style = SandyType.caption,
            color = SandyColors.secondaryText,
        )
        SandyButton(
            title = Localization.s("focus.stop"),
            onClick = { vm.stop(cancel = false) },
        )
        SandyButton(
            title = Localization.s("focus.cancel"),
            onClick = { vm.stop(cancel = true) },
        )
    }
}

// ── New-session setup ───────────────────────────────────────────────────────

@Composable
private fun SetupCard(onStart: (focusMin: Int, breakMin: Int, cycles: Int, label: String) -> Unit) {
    var label by remember { mutableStateOf("") }
    var focusMin by remember { mutableIntStateOf(25) }
    var breakMin by remember { mutableIntStateOf(5) }
    var cycles by remember { mutableIntStateOf(4) }

    Column(
        modifier = Modifier.fillMaxWidth().padding(top = Spacing.lg).sandyCard(),
        verticalArrangement = Arrangement.spacedBy(Spacing.md),
    ) {
        SandyTextField(label, { label = it }, Localization.s("focus.labelPlaceholder"))

        Stepper(Localization.s("focus.focusMin"), focusMin, step = 5, min = 5) { focusMin = it }
        Stepper(Localization.s("focus.breakMin"), breakMin, step = 1, min = 0) { breakMin = it }
        Stepper(Localization.s("focus.cycles"), cycles, step = 1, min = 1) { cycles = it }

        SandyButton(
            title = Localization.s("focus.start"),
            onClick = { onStart(focusMin, breakMin, cycles, label) },
        )
    }
}

/** A labelled minus / value / plus stepper built from design-system tokens. */
@Composable
private fun Stepper(title: String, value: Int, step: Int, min: Int, onChange: (Int) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(title, style = SandyType.callout, color = SandyColors.secondaryText)
        Spacer(Modifier.weight(1f))
        IconButton(onClick = { onChange((value - step).coerceAtLeast(min)) }) {
            Icon(
                Icons.Filled.Remove,
                contentDescription = null,
                tint = SandyColors.accent,
                modifier = Modifier.size(IconSize.md),
            )
        }
        Text(
            value.toString(),
            style = SandyType.headline,
            color = SandyColors.primaryText,
            modifier = Modifier.padding(horizontal = Spacing.md),
        )
        IconButton(onClick = { onChange(value + step) }) {
            Icon(
                Icons.Filled.Add,
                contentDescription = null,
                tint = SandyColors.accent,
                modifier = Modifier.size(IconSize.md),
            )
        }
    }
}

// ── History ─────────────────────────────────────────────────────────────────

@Composable
private fun HistoryList(history: List<FocusSession>, loading: Boolean) {
    Text(
        Localization.s("focus.history"),
        style = SandyType.headline,
        color = SandyColors.primaryText,
        modifier = Modifier.padding(top = Spacing.lg, bottom = Spacing.sm),
    )
    Box(Modifier.fillMaxSize()) {
        if (history.isEmpty() && !loading) {
            Text(
                Localization.s("focus.empty"),
                style = SandyType.subheadline,
                color = SandyColors.secondaryText,
                modifier = Modifier.align(Alignment.Center),
            )
        }
        LazyColumn(
            contentPadding = PaddingValues(bottom = 100.dp),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            items(history) { session -> HistoryRow(session) }
        }
    }
}

@Composable
private fun HistoryRow(session: FocusSession) {
    Row(
        modifier = Modifier.fillMaxWidth().sandyCard(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.md),
    ) {
        Icon(
            if (session.completed) Icons.Filled.CheckCircle else Icons.Filled.StopCircle,
            contentDescription = null,
            tint = if (session.completed) SandyColors.success else SandyColors.secondaryText,
            modifier = Modifier.size(IconSize.lg),
        )
        Text(
            session.label.ifEmpty { Localization.s("focus.phase.focus") },
            style = SandyType.body,
            color = SandyColors.primaryText,
            modifier = Modifier.weight(1f),
        )
        Text(
            String.format(Locale.getDefault(), Localization.s("focus.minutesDone"), session.minutes),
            style = SandyType.headline,
            color = SandyColors.accent,
        )
    }
}

/** Seconds → "mm:ss" (clamped at zero). */
private fun clock(sec: Int): String {
    val s = sec.coerceAtLeast(0)
    return String.format(Locale.US, "%02d:%02d", s / 60, s % 60)
}
