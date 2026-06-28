package com.sandy.app.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * Sandy design colors — a 1:1 port of the iOS `Theme.Colors` (Theme.swift),
 * which itself mirrors the web palette (obsidian-near-black + electric blue).
 * Keep this the single source: every screen pulls from here.
 */
object SandyColors {
    val accent = Color(0xFF00D4FF)        // primary electric blue
    val accentSoft = Color(0xFF5FE3FF)    // lighter accent (glow/buttons)
    val accentDeep = Color(0xFF0096FF)    // deeper accent (borders/gradient end)
    val secondary = Color(0xFF39C6E2)     // calmer cyan — sparse secondary accents
    val spark = Color(0xFF00D4FF)         // Sandy spark — same as accent, limited use

    val background = Color(0xFF020508)    // screen background (obsidian)
    val card = Color(0xFF0A1422)          // card/surface background
    val surface = Color(0xFF0E1A2A)       // secondary surface (fields, chips)

    val userBubble = Color(0x2E00D4FF)    // chat user bubble — accent @ 0.18
    val sandyBubble = Color(0xFF0E1A2A)   // chat Sandy bubble — dark surface

    val primaryText = Color(0xFFF0FAFF)
    val secondaryText = Color(0xFF9DB2C6)
    val tertiaryText = Color(0xFF70838F)
    val onAccent = Color(0xFF02121C)      // text over the bright accent fill

    val border = Color(0x2E00D4FF)        // faint electric border — accent @ 0.18

    val success = Color(0xFF34E0B0)
    val warn = Color(0xFFFFB84D)          // friendly amber (replaces harsh red)
    val warnSoft = Color(0xFF2A1E0C)
    val danger = Color(0xFFFF6B6B)        // calm red for destructive actions
}
