import SwiftUI

// ─────────────────────────────────────────────────────────────────────────
//  QuickAddView — نافذة «إضافة سريعة» بطريقة غير الحكي مع ساندي.
//
//  الفكرة: عنصر واحد بالرئيسية يفتح نافذة منبثقة فيها شبكة خيارات بسيطة
//  (مهمة/تذكير/عادة/مصروف/يومية/تسوّق/رسالة مستقبلية). أول ما المستخدم يختار
//  نوع، تتحوّل نفس النافذة لورقة الإضافة الجاهزة تبعت ذاك النوع — فيكتب ويحفظ
//  مباشرة بلا ما يروح لتبويبها.
//
//  كيف تشتغل بلا تكرار: ورقة كل أداة (TaskSheet/ReminderSheet/…) صارت `internal`
//  ونعيد استعمالها هون كما هي. نملك نسخة ستور لكل نوع (مستقلة عن الشاشات)، فالحفظ
//  يضرب الباك‑إند مباشرة. ورقة الأداة نفسها SandyPopup، فما نلفّها بنافذة تانية —
//  نعرض إمّا الشبكة أو ورقة الأداة (نافذة وحدة دايماً، تتحوّل بنعومة).
//
//  iOS 16-safe — لا @Observable، لا APIs أحدث.
// ─────────────────────────────────────────────────────────────────────────

/// أنواع الإضافة السريعة — كل نوع يوصل لورقة أداته الجاهزة.
enum QuickAddKind: Int, CaseIterable, Identifiable {
    case task, reminder, habit, expense, journal, shopping, future

    var id: Int { rawValue }

    var icon: String {
        switch self {
        case .task:     return "checklist"
        case .reminder: return "bell.fill"
        case .habit:    return "flame.fill"
        case .expense:  return "creditcard.fill"
        case .journal:  return "book.closed.fill"
        case .shopping: return "cart.fill"
        case .future:   return "paperplane.fill"
        }
    }

    /// مفتاح عنوان موجود مسبقًا (لا نضيف مفاتيح l10n جديدة).
    var titleKey: String {
        switch self {
        case .task:     return "daily.tasks"
        case .reminder: return "daily.reminders"
        case .habit:    return "life.habits"
        case .expense:  return "life.expenses"
        case .journal:  return "life.journal"
        case .shopping: return "shopping.title"
        case .future:   return "daily.future"
        }
    }
}

/// نافذة الإضافة السريعة — شبكة اختيار تتحوّل لورقة الأداة المختارة.
struct QuickAddSheet: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    /// النوع المختار — nil يعني نعرض الشبكة، وغيره يعرض ورقة الأداة.
    @State private var kind: QuickAddKind? = nil

    // ستور مستقل لكل نوع (نفس أنماط التبويبات) — الحفظ يضرب الباك‑إند مباشرة.
    @StateObject private var tasks = TasksStore()
    @StateObject private var reminders = RemindersStore()
    @StateObject private var habits = HabitsStore()
    @StateObject private var expenses = ExpensesStore()
    @StateObject private var journal = JournalStore()
    @StateObject private var shopping = ShoppingStore()
    @StateObject private var future = FutureMessagesStore()

    /// مُنسّق ISO8601 لموعد المهمة (نفس تنسيق تبويب المهام).
    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    var body: some View {
        // نافذة وحدة دايمًا: إمّا الشبكة أو ورقة الأداة (تتحوّل بنعومة).
        Group {
            if let kind {
                toolSheet(for: kind)
            } else {
                chooser
            }
        }
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: kind)
    }

    // MARK: - شبكة الاختيار

    private var chooserTitle: String {
        lang.lang == .ar ? "إضافة سريعة" : "Quick Add"
    }

    private var chooser: some View {
        SandyPopup(title: chooserTitle) {
            LazyVGrid(
                columns: [
                    GridItem(.flexible(), spacing: Theme.Spacing.md),
                    GridItem(.flexible(), spacing: Theme.Spacing.md),
                ],
                spacing: Theme.Spacing.md
            ) {
                ForEach(QuickAddKind.allCases) { k in
                    Button {
                        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
                            kind = k
                        }
                    } label: {
                        VStack(spacing: Theme.Spacing.sm) {
                            Image(systemName: k.icon)
                                .font(.system(size: Theme.Icon.lg, weight: .semibold))
                                .foregroundColor(Theme.Colors.accent)
                            Text(lang.s(k.titleKey))
                                .font(Theme.Typography.subheadline)
                                .foregroundColor(Theme.Colors.primaryText)
                                .lineLimit(1)
                                .minimumScaleFactor(0.8)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Theme.Spacing.md)
                        .sandyCard()
                    }
                    .liquidGlassPress()
                }
            }
        }
    }

    // MARK: - ورقة الأداة المختارة (إعادة استعمال الأوراق الجاهزة)

    @ViewBuilder
    private func toolSheet(for kind: QuickAddKind) -> some View {
        switch kind {
        case .task:
            TaskSheet { text, due, note, priority in
                let dueISO = due.map { Self.iso.string(from: $0) } ?? ""
                let trimmedNote = note.trimmingCharacters(in: .whitespacesAndNewlines)
                return await tasks.add(
                    api: state.api,
                    text: text.trimmingCharacters(in: .whitespacesAndNewlines),
                    due: dueISO,
                    note: trimmedNote.isEmpty ? nil : trimmedNote,
                    priority: priority)
            }
        case .reminder:
            ReminderSheet { text, remindAt, note in
                try await reminders.add(api: state.api, text: text, remindAt: remindAt, note: note)
            }
        case .habit:
            HabitSheet { name in
                try await habits.add(api: state.api, name: name)
            }
        case .expense:
            ExpenseSheet { amount, note, category in
                try await expenses.add(api: state.api, amount: amount, note: note, category: category)
            }
        case .journal:
            JournalSheet { text in
                try await journal.add(api: state.api, text: text)
            }
        case .shopping:
            ShoppingSheet { text, category in
                await shopping.add(api: state.api, text: text, category: category)
            }
        case .future:
            FutureMessageSheet { text, deliverAt in
                await future.add(api: state.api, text: text, deliverAt: deliverAt)
            }
        }
    }
}
