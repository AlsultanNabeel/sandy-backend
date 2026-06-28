package com.sandy.app.ui.theme

import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * Typography tokens — port of iOS `Theme.Typography`. We rely on the system font
 * (great Arabic support). iOS uses a rounded design face; Android's default sans
 * is the closest system equivalent, so we keep weights/sizes identical.
 */
object SandyType {
    val largeTitle = TextStyle(fontSize = 28.sp, fontWeight = FontWeight.Bold)
    val title = TextStyle(fontSize = 22.sp, fontWeight = FontWeight.Bold)
    val headline = TextStyle(fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
    val body = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.Normal)
    val callout = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.Medium)
    val subheadline = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Normal)
    val caption = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Normal)
    val button = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
}
