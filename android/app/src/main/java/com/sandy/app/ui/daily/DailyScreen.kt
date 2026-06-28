package com.sandy.app.ui.daily

import androidx.compose.runtime.Composable
import com.sandy.app.data.ApiClient
import com.sandy.app.ui.daily.tasks.TasksScreen

/**
 * Daily tab — planning. Tasks first; reminders, habits and focus join it as a
 * hub in later sessions. For now the tab shows Tasks directly.
 */
@Composable
fun DailyScreen(api: ApiClient) = TasksScreen(api)
