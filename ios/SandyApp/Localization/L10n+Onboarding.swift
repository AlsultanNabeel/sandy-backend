import Foundation

// Namespace: onboarding — first-run flow (meet Sandy → what she does → your name
// and interests → permissions). Paged, short, and every string lives here (ar + en).
//
// Usage:  Text(lang.s("onboarding.welcomeTitle"))
enum L10nOnboarding {
    static let ns = "onboarding"

    static let table = L10nTable(
        ar: [
            // شريط التنقّل
            "skip":              .text("تخطّي"),
            "next":              .text("التالي"),
            "back":              .text("رجوع"),
            "progress":          .text("التقدّم"),
            "save":              .text("يلا نبدأ"),

            // صفحة ١ — تعرّف على ساندي
            "welcomeTitle":      .text("أهلين، أنا ساندي"),
            "welcomeBody":       .text("رفيقتك اللي بتسمعك، بتتذكّرك، وبتساعدك تمشّي يومك بهدوء."),

            // صفحة ٢ — شو بتعمل
            "featuresTitle":     .text("شو بعمل معك؟"),
            "featChatTitle":     .text("حكي وصوت بيتذكّروك"),
            "featChatBody":      .text("احكيني كتابة أو بصوتك، وأنا بتذكّر اللي بيهمّك."),
            "featTasksTitle":    .text("مهام وتذكيرات وتركيز"),
            "featTasksBody":     .text("بنظّملك يومك، بذكّرك بوقتك، وبساعدك تركّز."),
            "featRobotTitle":    .text("الروبوت بالبيت"),
            "featRobotBody":     .text("وصّل روبوت ساندي وخلّيني معك بالبيت كمان."),

            // صفحة ٣ — اسمك واهتماماتك
            "title":             .text("خلّينا نتعرّف"),
            "nameLabel":         .text("شو تحب ساندي تناديك؟"),
            "namePlaceholder":   .text("اسمك المفضّل"),
            "interestsLabel":    .text("شو بيهمّك؟"),
            "interestsHint":     .text("اختار اللي بيعنيلك أو ضيف اهتمامك."),
            "interestsPlaceholder": .text("ضيف اهتمام…"),
            "add":               .text("إضافة"),
            "suggestions":       .items(["قراءة", "رياضة", "سفر", "طبخ", "موسيقى",
                                         "تقنية", "أفلام", "تصوير", "ألعاب", "تعلّم لغات"]),

            // صفحة ٤ — الأذونات
            "permsTitle":        .text("آخر خطوة"),
            "permsBody":         .text("بطلب الإذن بس لما تكبس «اسمح»، وبتقدر تغيّره أي وقت من الإعدادات."),
            "notifTitle":        .text("الإشعارات"),
            "notifBody":         .text("عشان أذكّرك بمهامك ومواعيدك بوقتها."),
            "micTitle":          .text("الميكروفون"),
            "micBody":           .text("عشان تحكيني بصوتك بدل الكتابة."),
            "allow":             .text("اسمح"),
            "notNow":            .text("مش هلّق"),
            "granted":           .text("مفعّل"),
            "denied":            .text("مقفول"),
            "later":             .text("لاحقًا"),
            "openSettings":      .text("الإعدادات"),
        ],
        en: [
            // Navigation
            "skip":              .text("Skip"),
            "next":              .text("Next"),
            "back":              .text("Back"),
            "progress":          .text("Progress"),
            "save":              .text("Let's start"),

            // Page 1 — meet Sandy
            "welcomeTitle":      .text("Hi, I'm Sandy"),
            "welcomeBody":       .text("Your companion who listens, remembers you, and helps your day run calmly."),

            // Page 2 — what she does
            "featuresTitle":     .text("What I do with you"),
            "featChatTitle":     .text("Chat and voice that remember you"),
            "featChatBody":      .text("Type or talk to me — I keep track of what matters to you."),
            "featTasksTitle":    .text("Tasks, reminders and focus"),
            "featTasksBody":     .text("I organise your day, remind you on time, and help you focus."),
            "featRobotTitle":    .text("The robot at home"),
            "featRobotBody":     .text("Pair the Sandy robot and I'm with you at home too."),

            // Page 3 — your name and interests
            "title":             .text("Let's get acquainted"),
            "nameLabel":         .text("What would you like Sandy to call you?"),
            "namePlaceholder":   .text("Your preferred name"),
            "interestsLabel":    .text("What are you into?"),
            "interestsHint":     .text("Pick what speaks to you, or add your own."),
            "interestsPlaceholder": .text("Add an interest…"),
            "add":               .text("Add"),
            "suggestions":       .items(["Reading", "Sports", "Travel", "Cooking", "Music",
                                         "Tech", "Movies", "Photography", "Gaming", "Languages"]),

            // Page 4 — permissions
            "permsTitle":        .text("One last thing"),
            "permsBody":         .text("I only ask when you tap Allow, and you can change it any time in Settings."),
            "notifTitle":        .text("Notifications"),
            "notifBody":         .text("So I can remind you about tasks and appointments on time."),
            "micTitle":          .text("Microphone"),
            "micBody":           .text("So you can talk to me instead of typing."),
            "allow":             .text("Allow"),
            "notNow":            .text("Not now"),
            "granted":           .text("Enabled"),
            "denied":            .text("Off"),
            "later":             .text("Later"),
            "openSettings":      .text("Settings"),
        ]
    )
}
