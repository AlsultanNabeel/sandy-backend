package com.sandy.app.i18n

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * Localization engine — Kotlin port of the iOS `Localization.swift` system.
 * Flat "namespace.key" lookups over an ar/en table, persisted choice in
 * SharedPreferences ("sandy_lang", default ar), Compose-observable `current`.
 *
 * Add a string by putting it under BOTH `ar` and `en` in [TABLE]. As features
 * are ported, their namespaces grow here (one table, mirrors the web/iOS dict).
 */
object Localization {

    /** "ar" | "en" — drives layout direction and the chat request language. */
    var current by mutableStateOf("ar")
        private set

    /** Plain accessor for non-Compose code (e.g. ApiClient). */
    val lang: String get() = current

    val isRtl: Boolean get() = current == "ar"

    private const val PREFS = "sandy_prefs"
    private const val KEY_LANG = "sandy_lang"
    private var prefs: android.content.SharedPreferences? = null

    fun init(context: Context) {
        val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        prefs = p
        current = p.getString(KEY_LANG, "ar") ?: "ar"
    }

    fun setLang(lang: String) {
        if (lang == current) return
        current = lang
        prefs?.edit()?.putString(KEY_LANG, lang)?.apply()
    }

    fun toggle() = setLang(if (current == "ar") "en" else "ar")

    /** Look up "namespace.key" for the current language; falls back to ar, then the key. */
    fun s(key: String): String {
        val byLang = TABLE[current] ?: TABLE["ar"]!!
        return byLang[key] ?: TABLE["ar"]?.get(key) ?: key
    }

    private val TABLE: Map<String, Map<String, String>> = mapOf(
        "ar" to mapOf(
            // tabs
            "tabs.home" to "الرئيسية",
            "tabs.sandy" to "ساندي",
            "tabs.daily" to "يومي",
            "tabs.life" to "حياتي",
            // common
            "common.language" to "اللغة",
            "common.loading" to "لحظة…",
            "common.retry" to "حاول مرّة ثانية",
            "common.save" to "حفظ",
            "common.cancel" to "إلغاء",
            "common.add" to "إضافة",
            "common.delete" to "حذف",
            "common.error" to "صار خطأ، جرّب كمان مرّة",
            // tasks
            "tasks.title" to "المهام",
            "tasks.addPlaceholder" to "أضف مهمة…",
            "tasks.empty" to "ما في مهام، أضف وحدة",
            "tasks.active" to "النشطة",
            "tasks.completed" to "المنجزة",
            "tasks.pickDate" to "موعد",
            "tasks.noDue" to "بلا موعد",
            // reminders
            "reminders.title" to "التذكيرات",
            "reminders.addPlaceholder" to "أضف تذكير…",
            "reminders.empty" to "ما في تذكيرات، أضف وحدة",
            "reminders.recurring" to "متكرر",
            "reminders.pickDate" to "اليوم",
            "reminders.pickTime" to "الوقت",
            "reminders.pastError" to "لازم يكون الوقت بالمستقبل",
            // habits
            "habits.title" to "العادات",
            "habits.addPlaceholder" to "أضف عادة…",
            "habits.empty" to "ما في عادات، ابدأ وحدة",
            "habits.streak" to "%d يوم متتالي",
            "habits.noStreak" to "ابدأ اليوم",
            "habits.doneToday" to "تمّت اليوم",
            // focus (Pomodoro)
            "focus.title" to "الفوكس",
            "focus.start" to "ابدأ",
            "focus.stop" to "إيقاف",
            "focus.cancel" to "إلغاء",
            "focus.focusMin" to "دقائق التركيز",
            "focus.breakMin" to "دقائق الراحة",
            "focus.cycles" to "الجولات",
            "focus.label" to "العنوان",
            "focus.labelPlaceholder" to "على شو تشتغل؟",
            "focus.phase.focus" to "تركيز",
            "focus.phase.break" to "راحة",
            "focus.history" to "السجل",
            "focus.empty" to "ما في جلسات بعد",
            "focus.running" to "جلسة شغّالة",
            "focus.cycleOf" to "جولة %1\$d من %2\$d",
            "focus.minutesDone" to "%d دقيقة",
            // expenses
            "expenses.title" to "المصاريف",
            "expenses.addPlaceholder" to "وش صرفت؟",
            "expenses.amount" to "المبلغ",
            "expenses.category" to "التصنيف",
            "expenses.note" to "ملاحظة",
            "expenses.empty" to "ما في مصاريف بعد",
            "expenses.total" to "المجموع",
            "expenses.count" to "العدد",
            // journal
            "journal.title" to "اليوميات",
            "journal.addPlaceholder" to "كيف كان يومك؟",
            "journal.empty" to "ابدأ أول تدوينة",
            "journal.edit" to "تعديل",
            // chat
            "chat.title" to "ساندي",
            "chat.placeholder" to "اكتب رسالة…",
            "chat.send" to "إرسال",
            "chat.empty" to "ابدأ المحادثة مع ساندي",
            "chat.newConversation" to "محادثة جديدة",
            "chat.history" to "السجل",
            "chat.rename" to "إعادة تسمية",
            "chat.delete" to "حذف",
            "chat.search" to "بحث بالمحادثات",
            "chat.untitled" to "بلا عنوان",
            "chat.thinking" to "ساندي تكتب…",
            // life hub
            "life.expenses" to "المصاريف",
            "life.journal" to "اليوميات",
            // auth
            "auth.welcome" to "أهلاً فيك بساندي",
            "auth.subtitle" to "مساعدتك الذكية لكل يومك",
            "auth.email" to "الإيميل",
            "auth.password" to "كلمة السر",
            "auth.login" to "دخول",
            "auth.signup" to "حساب جديد",
            "auth.google" to "تسجيل الدخول بجوجل",
            "auth.or" to "أو",
            "auth.error.generic" to "صار خطأ، جرّب كمان مرّة",
            // home / placeholders
            "home.title" to "الرئيسية",
            "home.greeting" to "أهلاً",
            "sandy.title" to "ساندي",
            "daily.title" to "يومي",
            "life.title" to "حياتي",
            "common.comingSoon" to "قريباً",
        ),
        "en" to mapOf(
            "tabs.home" to "Home",
            "tabs.sandy" to "Sandy",
            "tabs.daily" to "Daily",
            "tabs.life" to "Life",
            "common.language" to "Language",
            "common.loading" to "One moment…",
            "common.retry" to "Try again",
            "common.save" to "Save",
            "common.cancel" to "Cancel",
            "common.add" to "Add",
            "common.delete" to "Delete",
            "common.error" to "Something went wrong, try again",
            "tasks.title" to "Tasks",
            "tasks.addPlaceholder" to "Add a task…",
            "tasks.empty" to "No tasks yet — add one",
            "tasks.active" to "Active",
            "tasks.completed" to "Completed",
            "tasks.pickDate" to "Due",
            "tasks.noDue" to "No date",
            "reminders.title" to "Reminders",
            "reminders.addPlaceholder" to "Add a reminder…",
            "reminders.empty" to "No reminders yet — add one",
            "reminders.recurring" to "Recurring",
            "reminders.pickDate" to "Date",
            "reminders.pickTime" to "Time",
            "reminders.pastError" to "Time must be in the future",
            "habits.title" to "Habits",
            "habits.addPlaceholder" to "Add a habit…",
            "habits.empty" to "No habits yet — start one",
            "habits.streak" to "%d day streak",
            "habits.noStreak" to "Start today",
            "habits.doneToday" to "Done today",
            "focus.title" to "Focus",
            "focus.start" to "Start",
            "focus.stop" to "Stop",
            "focus.cancel" to "Cancel",
            "focus.focusMin" to "Focus minutes",
            "focus.breakMin" to "Break minutes",
            "focus.cycles" to "Cycles",
            "focus.label" to "Label",
            "focus.labelPlaceholder" to "What are you working on?",
            "focus.phase.focus" to "Focus",
            "focus.phase.break" to "Break",
            "focus.history" to "History",
            "focus.empty" to "No sessions yet",
            "focus.running" to "Session running",
            "focus.cycleOf" to "Cycle %1\$d of %2\$d",
            "focus.minutesDone" to "%d min",
            "expenses.title" to "Expenses",
            "expenses.addPlaceholder" to "What did you spend on?",
            "expenses.amount" to "Amount",
            "expenses.category" to "Category",
            "expenses.note" to "Note",
            "expenses.empty" to "No expenses yet",
            "expenses.total" to "Total",
            "expenses.count" to "Count",
            "journal.title" to "Journal",
            "journal.addPlaceholder" to "How was your day?",
            "journal.empty" to "Write your first entry",
            "journal.edit" to "Edit",
            "chat.title" to "Sandy",
            "chat.placeholder" to "Type a message…",
            "chat.send" to "Send",
            "chat.empty" to "Start chatting with Sandy",
            "chat.newConversation" to "New conversation",
            "chat.history" to "History",
            "chat.rename" to "Rename",
            "chat.delete" to "Delete",
            "chat.search" to "Search conversations",
            "chat.untitled" to "Untitled",
            "chat.thinking" to "Sandy is typing…",
            "life.expenses" to "Expenses",
            "life.journal" to "Journal",
            "auth.welcome" to "Welcome to Sandy",
            "auth.subtitle" to "Your smart helper for every day",
            "auth.email" to "Email",
            "auth.password" to "Password",
            "auth.login" to "Log in",
            "auth.signup" to "Sign up",
            "auth.google" to "Sign in with Google",
            "auth.or" to "or",
            "auth.error.generic" to "Something went wrong, try again",
            "home.title" to "Home",
            "home.greeting" to "Hi",
            "sandy.title" to "Sandy",
            "daily.title" to "Daily",
            "life.title" to "Life",
            "common.comingSoon" to "Coming soon",
        ),
    )
}
