package com.sandy.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.sandy.app.i18n.Localization
import com.sandy.app.ui.SandyApp
import com.sandy.app.ui.theme.SandyTheme

/** Single-activity entry point — hosts the whole Compose app. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Localization.init(applicationContext)
        enableEdgeToEdge()
        setContent {
            SandyTheme {
                SandyApp()
            }
        }
    }
}
