import SwiftUI
import UIKit

/// بطاقة على لوح.
///
/// `designHeight` هو ارتفاعها وهي بعرض اللوح كامل — يعني شكلها الطبيعي. كل
/// المقاسات التانية هي هاد مضروب بمعامل، فما في قياس ولا إعادة حساب: منعرف
/// الارتفاع قبل ما نرسم، واللوح بيرتّب حاله بمرّة وحدة.
struct BoardCard: Identifiable, BoardIdentifiable {
    let id: String
    let titleKey: String
    let icon: String
    let designHeight: CGFloat
    /// المقاس اللي بتبدأ فيه. واحد يعني عرض اللوح كامل.
    let defaultScale: Double
    let content: AnyView

    var boardID: String { id }

    init<C: View>(_ id: String,
                  titleKey: String,
                  icon: String = "square",
                  designHeight: CGFloat = 180,
                  defaultScale: Double = 1.0,
                  @ViewBuilder content: () -> C) {
        self.id = id
        self.titleKey = titleKey
        self.icon = icon
        self.designHeight = designHeight
        self.defaultScale = defaultScale
        self.content = AnyView(content())
    }
}

@resultBuilder
enum BoardBuilder {
    static func buildBlock(_ p: [BoardCard]...) -> [BoardCard] { p.flatMap { $0 } }
    static func buildExpression(_ c: BoardCard) -> [BoardCard] { [c] }
    static func buildExpression(_ c: [BoardCard]) -> [BoardCard] { c }
    static func buildOptional(_ c: [BoardCard]?) -> [BoardCard] { c ?? [] }
    static func buildEither(first c: [BoardCard]) -> [BoardCard] { c }
    static func buildEither(second c: [BoardCard]) -> [BoardCard] { c }
    static func buildArray(_ c: [[BoardCard]]) -> [BoardCard] { c.flatMap { $0 } }
}

/// أين استقرّت كل بطاقة على اللوح — لازم عشان نعرف فوق مين إيدك.
private struct CardFrames: PreferenceKey {
    static var defaultValue: [String: CGRect] = [:]
    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
        value.merge(nextValue()) { _, new in new }
    }
}

/// لوح بطاقات — كل بطاقة بأي حجم، وبأي ترتيب.
///
/// **الطريقة اللي بيشتغل فيها الآيفون، مش `onDrag`.** أول نسخة استعملت
/// `onDrag`/`onDrop`، وهاي آلية النقل بين التطبيقات: بدها ضغطة طويلة، بتعمل
/// صورة شبح، وبتتخانق مع التمرير — فالبطاقة ما كانت تنمسك، والصفحة كانت تمرق
/// تحت الإصبع. الشاشة الرئيسية بالآيفون ما بتستعمل شي من هاد: البطاقة بتمشي مع
/// إصبعك مباشرة، والباقي بيفتح لها مكان وهي جاية.
///
/// فهون: إيماءة سحب عادية بتحرّك البطاقة، وموقع إصبعك بيتقارن بمواقع الباقي
/// (`CardFrames`) وبيعيد الترتيب وقتها — بتشوف النتيجة قبل ما تفلت.
///
/// **والتمرير التلقائي جزء من السحب مش إضافة عليه.** لمّا توصل لطرف الشاشة
/// وإنت ماسك، الصفحة بتمشي معك؛ بلاه ما بتقدر تنقل بطاقة لمكان مش ظاهر، وهاد
/// بيخلي الترتيب شغّال ع الصفحات القصيرة وبس.
struct CardBoard: View {
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store: BoardStore

    private let cards: [BoardCard]

    @State private var frames: [String: CGRect] = [:]
    @State private var dragID: String?
    @State private var dragDelta: CGSize = .zero
    @State private var edgeTimer: Timer?
    @State private var scroll: ScrollViewProxy?

    @State private var resizeID: String?
    @State private var resizeBase: Double = 1

    init(_ screen: String, @BoardBuilder cards: () -> [BoardCard]) {
        _store = StateObject(wrappedValue: BoardStore(screen))
        self.cards = cards()
    }

    private let gap = Theme.Spacing.md

    /// كم قريب من الطرف لازم توصل حتى تبدأ الصفحة تمشي معك.
    private let edgeZone: CGFloat = 90

    private var ordered: [BoardCard] { store.arrange(cards) }

    var body: some View {
        GeometryReader { geo in
            let boardWidth = geo.size.width - gap * 2

            ScrollViewReader { proxy in
                ScrollView {
                    FlowLayout(gap: gap) {
                        ForEach(ordered) { card in
                            cell(card, boardWidth: boardWidth)
                                .id(card.id)
                        }
                    }
                    .padding(gap)

                    Color.clear.frame(height: 96)   // مساحة تحت ساندي العائمة
                }
                // وإنت ماسك بطاقة، إصبعك بتحرّكها هي مش الصفحة. التمرير بيصير
                // من الأطراف تلقائيًا — لو ضلّ شغّال كمان، التنين بيتحرّكوا سوا
                // والنتيجة إنك بتفقد البطاقة.
                .scrollDisabled(dragID != nil || resizeID != nil)
                .onPreferenceChange(CardFrames.self) { frames = $0 }
                .onChange(of: dragID) { _, id in
                    if id == nil { stopEdgeScroll() }
                }
                .onAppear { scroll = proxy }
            }
        }
        .toolbar { ToolbarItem(placement: .topBarTrailing) { editButton } }
    }

    // ── البطاقة ──────────────────────────────────────────────────────────────

    private func cell(_ card: BoardCard, boardWidth: CGFloat) -> some View {
        let s: Double = store.scale(card.id, default: card.defaultScale)
        let w: CGFloat = boardWidth * s
        let h: CGFloat = card.designHeight * s
        let held: Bool = dragID == card.id

        return card.content
            .frame(width: boardWidth, height: card.designHeight, alignment: .topLeading)
            .clipped()
            .scaleEffect(s, anchor: .topLeading)
            .frame(width: w, height: h, alignment: .topLeading)
            .allowsHitTesting(!store.editing)
            .background(
                RoundedRectangle(cornerRadius: Theme.Radius.card)
                    .fill(store.editing ? Theme.Colors.surface.opacity(0.35) : .clear)
            )
            .overlay(alignment: .topLeading) { if store.editing { nameTag(card) } }
            .overlay(alignment: .bottomTrailing) {
                if store.editing { grip(card, boardWidth: boardWidth) }
            }
            .overlay {
                if store.editing {
                    RoundedRectangle(cornerRadius: Theme.Radius.card)
                        .strokeBorder(Theme.Colors.accent.opacity(0.55),
                                      style: StrokeStyle(lineWidth: 1.5, dash: [5, 4]))
                }
            }
            // مواقع البطاقات — منها منعرف فوق مين إيدك وقت السحب.
            .background(
                GeometryReader { g in
                    Color.clear.preference(
                        key: CardFrames.self,
                        value: [card.id: g.frame(in: .global)])
                }
            )
            .scaleEffect(held ? 1.06 : 1)          // بترتفع تحت الإصبع
            .shadow(color: .black.opacity(held ? 0.28 : 0), radius: held ? 14 : 0, y: 6)
            .offset(held ? dragDelta : .zero)
            .zIndex(held ? 1 : 0)
            .contentShape(Rectangle())
            // `.gesture(cond ? g : nil)` ما بتترجم — النوعان مختلفان. الشرط
            // بيروح جوّا الإيماءة نفسها كـ `isEnabled`.
            .gesture(reorderGesture(card),
                     isEnabled: store.editing && resizeID == nil)
            .animation(.spring(response: 0.28, dampingFraction: 0.8), value: ordered.map(\.id))
    }

    // ── السحب لإعادة الترتيب ─────────────────────────────────────────────────

    private func reorderGesture(_ card: BoardCard) -> some Gesture {
        DragGesture(minimumDistance: 6, coordinateSpace: .global)
            .onChanged { g in
                if dragID != card.id {
                    dragID = card.id
                    UIImpactFeedbackGenerator(style: .light).impactOccurred()
                }
                dragDelta = g.translation
                moveIfHovering(over: g.location, held: card.id)
                edgeScrollIfNeeded(at: g.location)
            }
            .onEnded { _ in
                dragID = nil
                dragDelta = .zero
                stopEdgeScroll()
                store.setOrder(ordered.map(\.id))
            }
    }

    /// البطاقة اللي تحت إصبعك بتفسح، وقت ما تمرق فوقها.
    ///
    /// الترتيب بيصير وقت المرور مش وقت الإفلات: بتشوف المكان الجديد وإنت لسا
    /// ماسك، فما بتحتاج تفلت وتشوف وين وقعت وتعيد.
    private func moveIfHovering(over point: CGPoint, held: String) {
        guard let targetID = frames.first(where: { $0.value.contains(point) })?.key,
              targetID != held else { return }
        var ids: [String] = ordered.map(\.id)
        guard let from = ids.firstIndex(of: held),
              let to = ids.firstIndex(of: targetID) else { return }
        ids.move(fromOffsets: IndexSet(integer: from), toOffset: to > from ? to + 1 : to)
        // بلا حفظ: السحب بيولّد عشرات النداءات بالثانية، وكتابة القرص مع كل
        // وحدة بتخلّي الإصبع تتعتّر. الحفظ لما ترفع إيدك.
        store.setOrderLive(ids)
    }

    // ── التمرير من الأطراف ───────────────────────────────────────────────────

    private func edgeScrollIfNeeded(at point: CGPoint) {
        guard let held = dragID else { return }
        // الإحداثيات عالمية (إحداثيات الشاشة)، فالمقارنة مباشرة بلا تخمين.
        // أول نسخة حاولت تحسب كم مرقنا من مواقع البطاقات — تقدير، وبيغلط أول ما
        // يتغيّر أي إشي بالتخطيط.
        let screenH: CGFloat = UIScreen.main.bounds.height
        let goingUp: Bool = point.y < edgeZone + 60      // تحت شريط العنوان
        let goingDown: Bool = point.y > screenH - edgeZone

        if goingUp || goingDown {
            startEdgeScroll(up: goingUp, held: held)
        } else {
            stopEdgeScroll()
        }
    }

    private func startEdgeScroll(up: Bool, held: String) {
        guard edgeTimer == nil else { return }
        edgeTimer = Timer.scheduledTimer(withTimeInterval: 0.12, repeats: true) { _ in
            Task { @MainActor in
                step(up: up, held: held)
            }
        }
    }

    @MainActor
    private func step(up: Bool, held: String) {
        let ids: [String] = ordered.map(\.id)
        guard let i = ids.firstIndex(of: held) else { return }
        let next: Int = up ? max(0, i - 1) : min(ids.count - 1, i + 1)
        guard next != i else { return }
        withAnimation(.easeInOut(duration: 0.15)) {
            scroll?.scrollTo(ids[next], anchor: up ? .top : .bottom)
        }
    }

    private func stopEdgeScroll() {
        edgeTimer?.invalidate()
        edgeTimer = nil
    }

    // ── التحجيم ──────────────────────────────────────────────────────────────

    /// مقبض الزاوية.
    ///
    /// **جوّا البطاقة، مش برّاها.** أول نسخة دفشته `offset(x: 8, y: 8)` عشان
    /// يطلع ع الزاوية، وسويفت‌يو‌آي ما بتوصّل اللمس لأي إشي واقع برّا إطار
    /// أبوه — فالمقبض كان بينرسم وما بينمسك، والتحجيم كان شكله ميزة موجودة
    /// وما بتشتغل.
    private func grip(_ card: BoardCard, boardWidth: CGFloat) -> some View {
        CornerGrip()
            .padding(4)
            // مساحة اللمس أوسع من الشكل: زاوية بعشرين نقطة صعب تمسكها بالإصبع،
            // خصوصًا ع بطاقة صغيرة. الشكل صغير والهدف كبير.
            .contentShape(Rectangle().inset(by: -12))
            // أولوية عالية: البطاقة كلها عليها إيماءة سحب للترتيب، وبلا هاد
            // السحب من الزاوية بيرتّب بدل ما يحجّم.
            .highPriorityGesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { g in
                        if resizeID != card.id {
                            resizeID = card.id
                            resizeBase = store.scale(card.id, default: card.defaultScale)
                        }
                        // القطر: بتقدر تسحب لبرّا أو لتحت أو للاتنين. ربطه
                        // بالعرض لحاله بيخلّي السحب لتحت ما يعمل إشي، وهاد
                        // بيبيّن عطل.
                        let d: CGFloat = (g.translation.width + g.translation.height) / 2
                        store.setScale(resizeBase + Double(d / boardWidth), for: card.id)
                    }
                    .onEnded { _ in
                        resizeID = nil
                        store.save()      // الحفظ لما ترفع إيدك، مش كل إطار
                    }
            )
            .accessibilityLabel(lang.s("board.resize"))
    }

    // ── الاسم وزر التعديل ────────────────────────────────────────────────────

    private func nameTag(_ card: BoardCard) -> some View {
        HStack(spacing: 4) {
            Image(systemName: card.icon).font(.system(size: 10, weight: .semibold))
            Text(lang.s(card.titleKey)).font(.system(size: 11, weight: .semibold))
                .lineLimit(1)
        }
        .foregroundColor(Theme.Colors.onAccent)
        .padding(.horizontal, 7).padding(.vertical, 4)
        .background(Capsule().fill(Theme.Colors.accent))
        .padding(5)
    }

    private var editButton: some View {
        HStack(spacing: Theme.Spacing.sm) {
            if store.editing && store.isCustomised {
                Button(lang.s("board.reset")) { withAnimation { store.reset() } }
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
            }
            Button {
                withAnimation(.spring(response: 0.3, dampingFraction: 0.85)) {
                    store.editing.toggle()
                }
                if !store.editing { store.save() }
            } label: {
                Image(systemName: store.editing
                      ? "checkmark.circle.fill" : "slider.horizontal.3")
                    .foregroundColor(Theme.Colors.accent)
            }
            .accessibilityLabel(lang.s(store.editing ? "board.done" : "board.edit"))
        }
    }
}

/// رصف البطاقات بسطور — بطاقة جنب بطاقة لحدّ ما يمتلي السطر.
///
/// `Layout` مش VStack من HStackات: الأعراض بتتحسب مرّة وحدة من مقاسات معروفة
/// مسبقًا، بلا قياس ولا تمريرة تانية. هاد اللي بيخلّي السحب سلس — كل إطار
/// بيحرّك مواقع محسوبة، مش بيعيد بناء شجرة.
private struct FlowLayout: Layout {
    let gap: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews,
                      cache: inout Void) -> CGSize {
        let maxW: CGFloat = proposal.width ?? 400
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowH: CGFloat = 0
        for v in subviews {
            let s: CGSize = v.sizeThatFits(.unspecified)
            if x > 0 && x + s.width > maxW {
                x = 0
                y += rowH + gap
                rowH = 0
            }
            x += s.width + gap
            rowH = max(rowH, s.height)
        }
        return CGSize(width: maxW, height: y + rowH)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize,
                       subviews: Subviews, cache: inout Void) {
        var x: CGFloat = bounds.minX
        var y: CGFloat = bounds.minY
        var rowH: CGFloat = 0
        for v in subviews {
            let s: CGSize = v.sizeThatFits(.unspecified)
            if x > bounds.minX && x + s.width > bounds.maxX {
                x = bounds.minX
                y += rowH + gap
                rowH = 0
            }
            v.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
            x += s.width + gap
            rowH = max(rowH, s.height)
        }
    }
}

/// مقبض التحجيم — زاوية غامقة، زي نظام أبل.
///
/// كان سهمًا داخل دائرة ملوّنة. السهم بيقول «اسحبني» بالكلام، والزاوية بتقولها
/// بالشكل: هي حرفيًا زاوية البطاقة، فبتعرف إنك بتشدّ الزاوية بلا ما حدا يشرحلك.
/// وهاد اللي بيخلّي عنصر تحكّم يبيّن جزء من النظام مش ملصق فوقه.
///
/// غامق مش ملوّن عن قصد: اللون بيسحب العين لعنصر تحكّم المفروض يستنّى دورك.
/// وبيقعد فوق أي محتوى — صورة فاتحة أو بطاقة غامقة — لأنه إله خلفيته وحدّه
/// الفاتح الرفيع.
private struct CornerGrip: View {
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(.black.opacity(0.55))
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(.ultraThinMaterial)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(.white.opacity(0.35), lineWidth: 0.5)
                )

            CornerBracket()
                .stroke(.white.opacity(0.95),
                        style: StrokeStyle(lineWidth: 2, lineCap: .round,
                                           lineJoin: .round))
                .frame(width: 11, height: 11)
        }
        .frame(width: 26, height: 26)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .shadow(color: .black.opacity(0.25), radius: 3, y: 1)
    }
}

/// زاوية «⌟» — ضلعان بيلتقوا تحت-يمين.
private struct CornerBracket: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: rect.maxX, y: rect.minY))
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        p.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        return p
    }
}
