import Foundation

// Namespace: home — the live Home tab (HomeView). Mirrors the web dict/home.js
// (kept flat). FILLED.
//
// Usage:  Text(lang.s("home.greeting.morning"))
//         ForEach(lang.list("home.encourage"), …)
//
// NOTES on key shapes:
//   • Most keys are plain `.text("…")`.
//   • "encourage" is the ONLY array key — `.items([...])` — read via lang.list.
//   • Format keys carry a `%@` placeholder and are filled in code via
//     String(format:). These are:
//       "greeting.name.suffix"  → " يا %@" / " %@"      (one %@)
//       "proactive.overdue"     → count + plural word    (two %@)
//       "proactive.today"       → count + plural word    (two %@)
//       "proactive.openTasks"   → count + plural word    (two %@)
//       "proactive.reminder"    → reminder text + when   (two %@)
//       "proactive.spendingHigh"→ formatted amount       (one %@)
//       "glance.today.overdue"  → count of overdue       (one %@)
//       "glance.spending.today" → today's amount         (one %@)
//       "reminder.sub.relative" → relative time string   (one %@)
enum L10nHome {
    static let ns = "home"

    static let table = L10nTable(
        ar: [
            // Nav / toolbar
            "title":            .text("ساندي"),
            "profile":          .text("حسابي"),
            "reorder":          .text("إعادة ترتيب العناصر"),
            "reorderTitle":     .text("ترتيب الرئيسية"),
            "reorderHint":      .text("اسحب العناصر لترتيبها كيف ما يناسبك."),
            "block.proactive":  .text("نظرة ساندي"),
            "block.glance":     .text("لمحة سريعة"),
            "block.talk":       .text("احكي مع ساندي"),

            // Greeting — time-of-day lines (+ name suffix, a format key)
            "greeting.morning":     .text("صباح الخير"),
            "greeting.afternoon":   .text("نهارك سعيد"),
            "greeting.evening":     .text("مساء الخير"),
            "greeting.night":       .text("سهرة هنيّة"),
            "greeting.name.suffix": .text(" يا %@"),
            "greeting.sub.morning":   .text("خلّينا نبدأ اليوم سوا."),
            "greeting.sub.afternoon": .text("كيف ماشي يومك لهلّأ؟"),
            "greeting.sub.evening":   .text("خلّينا نشوف شو ضل على اليوم."),
            "greeting.sub.night":     .text("آخر لمسة قبل ما ترتاح."),

            // Load failure notice
            "loadFailed": .text("معلش، تعثّرت وأنا أجمعلك يومك — اسحب لتحت تحدّث وأنا أعيد المحاولة 🌷"),

            // Proactive card ("نظرة ساندي")
            "proactive.title":       .text("نظرة ساندي"),
            "proactive.loading":     .text("لحظة، بجمعلك يومك…"),
            // format: %@ = count, %@ = singular/plural word
            "proactive.overdue":     .text("عندك %@ %@ متأخّرة — بتحب أرتّبهن إلك؟"),
            "proactive.today":       .text("اليوم قدّامك %@ %@، نبلّش فيهن؟"),
            // format: %@ = reminder text, %@ = when-suffix (may be empty)
            "proactive.reminder":    .text("مذكّرتك: %@%@."),
            // format: %@ = formatted amount
            "proactive.spendingHigh":.text("مصروف هالأسبوع وصل %@ — بنراجعه سوا لو حابب."),
            // format: %@ = count, %@ = singular/plural word
            "proactive.openTasks":   .text("ماشي حالك — عندك %@ %@ مفتوحة بس ولا وحدة مستعجلة اليوم."),

            // Proactive — rotating encouragement (ARRAY → lang.list)
            "encourage": .items([
                "كل شي تمام — يومك صافي وما في شي عالق. استمتع 🌿",
                "ولا مهمة متأخّرة وولا تذكير فايت — إنت ماسك زمام يومك 👏",
                "صفحتك بيضا اليوم — لو خطر ببالك أي شي، احكيلي وأنا أرتّبه.",
                "كل شي تحت السيطرة — خلّينا نخلّي اليوم يوم حلو."
            ]),

            // Proactive — small contextual action button titles
            "proactive.action.tasks":     .text("افتح مهامي"),
            "proactive.action.reminders": .text("افتح تذكيراتي"),
            "proactive.action.life":      .text("افتح حياتي"),
            "proactive.action.chat":      .text("احكي مع ساندي"),

            // Plural helper words (filled into the format keys above)
            "task.singular": .text("مهمة"),
            "task.plural":   .text("مهام"),

            // Floating Sandy contextual message
            "floating.overdue":  .text("عندك مهام متأخّرة — اضغط نرتّبهن سوا."),
            "floating.today":    .text("في مهام لليوم — نبلّش؟"),
            "floating.reminder": .text("عندك تذكير قادم — تحب تشوفه؟"),
            "floating.idle":     .text("محتاج شي؟ احكيلي وأنا جاهزة 🌷"),

            // Quick-glance section
            "glance.section":         .text("لمحة سريعة"),
            "glance.today.label":     .text("مهام اليوم"),
            // format: %@ = count of overdue
            "glance.today.overdue":   .text("%@ متأخّرة"),
            "glance.spending.label":  .text("مصروف الأسبوع"),
            // format: %@ = today's formatted amount
            "glance.spending.today":  .text("اليوم %@"),

            // Reminder wide card
            "reminder.none":          .text("ما في تذكير قادم"),
            "reminder.sub.add":       .text("اضغط تضيف تذكير جديد"),
            "reminder.sub.fallback":  .text("أقرب تذكير إلك"),
            // format: %@ = relative time
            "reminder.sub.relative":  .text("أقرب تذكير — %@"),

            // Talk-to-Sandy card
            "talk.title": .text("احكي مع ساندي"),
            "talk.body":  .text("احكيلي بأي شي — ضيف مهمة، ذكّرني، سجّل مصروف… أنا فهمانة عليك."),

            // Currency symbol (number is composed in code: "<num> ₪")
            "currency": .text("₪"),
        ],
        en: [
            // Nav / toolbar
            "title":            .text("Sandy"),
            "profile":          .text("My account"),
            "reorder":          .text("Reorder items"),
            "reorderTitle":     .text("Arrange home"),
            "reorderHint":      .text("Drag the items to order them however suits you."),
            "block.proactive":  .text("Sandy's take"),
            "block.glance":     .text("Quick glance"),
            "block.talk":       .text("Talk to Sandy"),

            // Greeting — time-of-day lines (+ name suffix, a format key)
            "greeting.morning":     .text("Good morning"),
            "greeting.afternoon":   .text("Good afternoon"),
            "greeting.evening":     .text("Good evening"),
            "greeting.night":       .text("Have a cozy evening"),
            "greeting.name.suffix": .text(", %@"),
            "greeting.sub.morning":   .text("Let's kick off the day together."),
            "greeting.sub.afternoon": .text("How's your day going so far?"),
            "greeting.sub.evening":   .text("Let's see what's left for today."),
            "greeting.sub.night":     .text("One last touch before you rest."),

            // Load failure notice
            "loadFailed": .text("Sorry, I stumbled while pulling your day together — pull down to refresh and I'll try again 🌷"),

            // Proactive card ("نظرة ساندي")
            "proactive.title":       .text("Sandy's take"),
            "proactive.loading":     .text("One sec, I'm pulling your day together…"),
            // format: %@ = count, %@ = singular/plural word
            "proactive.overdue":     .text("You have %@ overdue %@ — want me to sort them out for you?"),
            "proactive.today":       .text("You've got %@ %@ today — shall we start?"),
            // format: %@ = reminder text, %@ = when-suffix (may be empty)
            "proactive.reminder":    .text("Reminder: %@%@."),
            // format: %@ = formatted amount
            "proactive.spendingHigh":.text("This week's spending hit %@ — we can review it together if you like."),
            // format: %@ = count, %@ = singular/plural word
            "proactive.openTasks":   .text("You're doing fine — %@ open %@, but nothing urgent today."),

            // Proactive — rotating encouragement (ARRAY → lang.list)
            "encourage": .items([
                "All good — your day is clear and nothing's pending. Enjoy 🌿",
                "No overdue tasks, no missed reminders — you're on top of your day 👏",
                "Clean slate today — if anything comes to mind, tell me and I'll sort it.",
                "Everything's under control — let's make today a good one."
            ]),

            // Proactive — small contextual action button titles
            "proactive.action.tasks":     .text("Open my tasks"),
            "proactive.action.reminders": .text("Open my reminders"),
            "proactive.action.life":      .text("Open my life"),
            "proactive.action.chat":      .text("Talk to Sandy"),

            // Plural helper words (filled into the format keys above)
            "task.singular": .text("task"),
            "task.plural":   .text("tasks"),

            // Floating Sandy contextual message
            "floating.overdue":  .text("You have overdue tasks — tap and we'll sort them together."),
            "floating.today":    .text("There are tasks for today — shall we start?"),
            "floating.reminder": .text("You've got an upcoming reminder — want to see it?"),
            "floating.idle":     .text("Need anything? Tell me, I'm ready 🌷"),

            // Quick-glance section
            "glance.section":         .text("Quick glance"),
            "glance.today.label":     .text("Today's tasks"),
            // format: %@ = count of overdue
            "glance.today.overdue":   .text("%@ overdue"),
            "glance.spending.label":  .text("This week's spending"),
            // format: %@ = today's formatted amount
            "glance.spending.today":  .text("Today %@"),

            // Reminder wide card
            "reminder.none":          .text("No upcoming reminder"),
            "reminder.sub.add":       .text("Tap to add a new reminder"),
            "reminder.sub.fallback":  .text("Your nearest reminder"),
            // format: %@ = relative time
            "reminder.sub.relative":  .text("Nearest reminder — %@"),

            // Talk-to-Sandy card
            "talk.title": .text("Talk to Sandy"),
            "talk.body":  .text("Tell me anything — add a task, remind you, log an expense… I get you."),

            // Currency symbol (number is composed in code: "<num> ₪")
            "currency": .text("₪"),
        ]
    )
}
