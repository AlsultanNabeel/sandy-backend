import Foundation

struct ChatMessage: Identifiable {
    let id = UUID()
    let role: String   // "user" | "sandy"
    let text: String
}

// ── سجل المحادثات (متعدد السيشنات) — تطابق /api/conversations ───────────────

/// سطر بقائمة سجل المحادثات.
struct ConversationMeta: Identifiable {
    let id: String
    let title: String
    let updatedAt: String   // ISO
}

/// نتيجة بحث بالسجل — عنوان + مقتطف المطابقة.
struct ConversationHit: Identifiable {
    let id: String
    let title: String
    let snippet: String
    let updatedAt: String
}

struct OnboardingData {
    var done: Bool = false
    var preferredName: String = ""
    var interests: [String] = []
    var name: String = ""
}

// مهمة — تطابق مفاتيح GET /api/tasks: id, text, done, due_at, note, priority
// note و priority إضافيان واختياريان من الباك-إند — نعطيهما قيمًا افتراضية لو غابا.
struct TaskItem: Identifiable {
    let id: String
    let text: String
    var done: Bool
    let dueAt: String       // ISO أو فاضي
    var note: String = ""    // ملاحظة اختيارية
    var priority: String = "normal"   // "low" | "normal" | "high"
}

// تذكير — تطابق مفاتيح GET /api/reminders: id, text, remind_at, is_recurring, note
struct ReminderItem: Identifiable {
    let id: String
    let text: String
    let remindAt: String   // ISO أو فاضي
    let isRecurring: Bool
    var note: String = ""    // ملاحظة اختيارية
}

// عادة — تطابق مفاتيح GET /api/life/habits: id, name, streak, done_today
struct HabitItem: Identifiable {
    let id: String
    let name: String
    let streak: Int
    var doneToday: Bool
}

// مصروف — تطابق مفاتيح GET /api/life/expenses items[]: id, amount, note, category, at
struct ExpenseItem: Identifiable {
    let id: String
    let amount: Double
    let note: String
    let category: String
    let at: String   // ISO أو فاضي
}

// ملخّص المصاريف — تطابق summary: total, count
struct ExpensesSummary {
    let total: Double
    let count: Int
}

// تدوينة يوميات — تطابق مفاتيح GET /api/life/journal: id, date, text
struct JournalEntry: Identifiable {
    let id: String
    let date: String
    let text: String
}

/// نتيجة قائمة مع علامة بيانات التجربة (demo) — لعرض شريط "بيانات تجربة".
struct ListResult<T> {
    let items: [T]
    let demo: Bool
}

/// نتيجة المصاريف: عناصر + ملخّص + علامة التجربة.
struct ExpensesResult {
    let items: [ExpenseItem]
    let summary: ExpensesSummary
    let demo: Bool
}

/// لقطة الشاشة الرئيسية — تجميع خفيف من نداءات GET الموجودة (مهام/تذكيرات/مصاريف).
/// تُبنى بالكامل من البيانات المتاحة، بدون أي نقطة نهاية جديدة بالباك-إند.
/// كل قسم يتحمّل الفشل وحده: لو فشل قسم تبقى بقية الأقسام شغّالة.
struct HomeSnapshot {
    // المهام
    var overdueTasks: Int = 0        // مهام فات موعدها (due_at < الآن) وغير منجزة
    var todayTasks: Int = 0          // مهام موعدها اليوم وغير منجزة
    var openTasks: Int = 0           // إجمالي المهام المفتوحة (غير منجزة)
    var sampleTaskTexts: [String] = []   // عيّنة نصوص (حتى 3) للعرض

    // التذكيرات
    var nextReminderText: String = ""    // أقرب تذكير قادم (فاضي لو ما في)
    var nextReminderAt: String = ""      // وقته ISO (فاضي لو ما في)
    var upcomingReminders: [ReminderItem] = []   // عيّنة قادمة (حتى 3)

    // المصاريف
    var todayExpenseTotal: Double = 0    // مجموع مصاريف اليوم
    var weekExpenseTotal: Double = 0     // مجموع مصاريف آخر 7 أيام (أو ملخّص المدى)

    // الحالة العامة
    var demo: Bool = false               // أي قسم رجّع بيانات تجربة
    var hadError: Bool = false           // فشل قسم واحد على الأقل (نعرض بهدوء)
}

// ── الفوكس (بومودورو) + مشاهد الغرفة ──────────────────────────────────────

/// حالة جلسة فوكس — تطابق GET /api/life/focus.
struct FocusStatus {
    var active: Bool = false
    var label: String = ""
    var scene: String = ""
    var phase: String = "focus"     // "focus" | "break"
    var cycleIdx: Int = 1
    var cycles: Int = 1
    var focusMin: Int = 25
    var breakMin: Int = 0
    var remainingSec: Int = 0
    var totalSec: Int = 0
    var demo: Bool = false
    var isBreak: Bool { phase == "break" }
}

/// فعل ضمن مشهد — جهاز + قيمة (مثلاً light=60، music=on).
struct SceneAction: Identifiable, Equatable {
    var id = UUID()
    var device: String
    var value: String
}

/// مشهد غرفة — تطابق عناصر GET /api/life/scenes.
struct RoomScene: Identifiable {
    let name: String
    var label: String
    var icon: String
    var actions: [SceneAction]
    var id: String { name }
}

/// سطر تاريخ جلسة فوكس — تطابق عناصر GET /api/life/focus/history.
struct FocusSession: Identifiable {
    let id = UUID()
    let label: String
    let minutes: Int
    let completed: Bool
    let startedAt: String
}

// ── البحث الخارجي (الويب/الأماكن) — تطابق GET /api/research ─────────────────

/// نتيجة بحث ويب — تطابق عناصر kind=web: title, url, text, published_date.
struct WebResult: Identifiable {
    let id = UUID()
    let title: String
    let url: String
    let text: String
    let publishedDate: String
}

/// نتيجة مكان — تطابق عناصر kind=places من Google Places.
struct PlaceResult: Identifiable {
    let id = UUID()
    let name: String
    let address: String
    let rating: Double
    let reviewsCount: Int
    let phone: String
    let website: String
    let priceLevel: String
    let openNow: String
    let mapsUrl: String
}

struct APIError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

extension Error {
    /// طلب اتلغى (سحب-للريفرش انتهى، أو المستخدم طلع من الشاشة) — هاد سلوك طبيعي
    /// من النظام، مش فشل شبكة. أي معالج خطأ بالتطبيق لازم يتجاهله ولا يعرضه.
    var isCancellation: Bool {
        self is CancellationError || (self as? URLError)?.code == .cancelled
    }
}
