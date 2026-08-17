import SwiftUI

/// بطاقة على لوح.
///
/// `designHeight` هو ارتفاعها وهي بعرض اللوح كامل — يعني شكلها الطبيعي. كل
/// المقاسات التانية هي هاد مضروب بمعامل، فما في قياس ولا إعادة حساب: بنعرف
/// الارتفاع قبل ما نرسم، واللوح بيرتّب حاله بمرّة وحدة.
///
/// الرقم بيجي من اللي بيكتب البطاقة لأنه هو اللي بيعرف شو جواها. تقديره غلط
/// بيخلّي البطاقة تقصّ أو تترك فراغ — وهاد بينشاف فورًا وبينظبط برقم واحد.
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

/// لوح بطاقات — كل بطاقة بأي حجم، وبأي ترتيب.
///
/// **ليش مش شبكة:** الشبكة بتحصر المقاسات بخانات، والمالك طلب كل المقاسات. اللوح
/// بيرصف زي الكلام بالسطر — بطاقة جنب بطاقة لحدّ ما يمتلي السطر وبعدين ينزل —
/// فأي عرض بيلاقي مكانه، وما في خانات فاضية بتنترك ورا بطاقة عريضة.
///
/// **وليش وضع تعديل مستقل:** الصفحة مقروءة أغلب الوقت. لو كل بطاقة بتتحرّك بأي
/// ضغطة طويلة، الضغطة الطويلة بتنسرق من المحتوى نفسه وبتزحزح إشي وإنت بس بدك
/// تقرا.
struct CardBoard: View {
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store: BoardStore

    private let cards: [BoardCard]

    @State private var dragging: String?
    @State private var resizing: String?
    @State private var resizeBase: Double = 1

    init(_ screen: String, @BoardBuilder cards: () -> [BoardCard]) {
        _store = StateObject(wrappedValue: BoardStore(screen))
        self.cards = cards()
    }

    private let gap = Theme.Spacing.md

    var body: some View {
        GeometryReader { geo in
            let width = geo.size.width - gap * 2
            ScrollView {
                FlowRows(cards: store.arrange(cards), boardWidth: width, gap: gap) { card in
                    cell(card, boardWidth: width)
                }
                .padding(gap)

                Color.clear.frame(height: 96)   // مساحة تحت ساندي العائمة
            }
            // التمرير بينطفي وقت التحجيم: إصبعك نازلة ع الزاوية، وبلا هاد اللوح
            // بيمرق تحتها والبطاقة بتكبر بنفس الوقت.
            .scrollDisabled(resizing != nil)
        }
        .toolbar { ToolbarItem(placement: .topBarTrailing) { editButton } }
    }

    // ── البطاقة ──────────────────────────────────────────────────────────────

    private func cell(_ card: BoardCard, boardWidth: CGFloat) -> some View {
        let s = store.scale(card.id, default: card.defaultScale)

        // المحتوى بينرسم مرّة بمقاسه الطبيعي، وبعدين بينصغّر كتحويل رسومي.
        // ما في إعادة ترتيب جوّا البطاقة وقت السحب — عشان هيك بتضل سلسة مهما
        // كان جواها.
        return card.content
            .frame(width: boardWidth, height: card.designHeight, alignment: .topLeading)
            .clipped()
            .scaleEffect(s, anchor: .topLeading)
            .frame(width: boardWidth * s, height: card.designHeight * s,
                   alignment: .topLeading)
            .allowsHitTesting(!store.editing)
            .background(
                RoundedRectangle(cornerRadius: Theme.Radius.card)
                    .fill(store.editing ? Theme.Colors.surface.opacity(0.35) : .clear)
            )
            .overlay(alignment: .topLeading) { if store.editing { nameTag(card, scale: s) } }
            .overlay(alignment: .bottomTrailing) { if store.editing { grip(card, boardWidth: boardWidth) } }
            .overlay {
                if store.editing {
                    RoundedRectangle(cornerRadius: Theme.Radius.card)
                        .strokeBorder(Theme.Colors.accent.opacity(0.55),
                                      style: StrokeStyle(lineWidth: 1.5, dash: [5, 4]))
                }
            }
            .opacity(dragging == card.id ? 0.3 : 1)
            .contentShape(Rectangle())
            .modifier(Reorder(enabled: store.editing && resizing == nil,
                              id: card.id, dragging: $dragging,
                              onEnter: { moved in move(moved, before: card.id) }))
    }

    /// اسم البطاقة وقت التعديل — بمقاس ثابت مهما صغّرت.
    ///
    /// لو كان جزء من المحتوى المتناسب، أصغر بطاقة بيصير اسمها غير مقروء — وساعتها
    /// بتسحب مستطيلات ما بتعرف مين منهن.
    private func nameTag(_ card: BoardCard, scale: Double) -> some View {
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

    /// مقبض الزاوية. اسحبه لأي مقاس — ما في درجات ولا قفزات.
    private func grip(_ card: BoardCard, boardWidth: CGFloat) -> some View {
        Image(systemName: "arrow.down.right")
            .font(.system(size: 11, weight: .bold))
            .foregroundColor(Theme.Colors.onAccent)
            .frame(width: 26, height: 26)
            .background(Circle().fill(Theme.Colors.accent))
            .offset(x: 8, y: 8)
            // مساحة لمس أوسع من الشكل: مقبض بستّة وعشرين نقطة صعب تمسكه،
            // خصوصًا ع بطاقة صغيرة.
            .contentShape(Rectangle().inset(by: -14))
            .gesture(
                DragGesture(minimumDistance: 1)
                    .onChanged { g in
                        if resizing != card.id {
                            resizing = card.id
                            resizeBase = store.scale(card.id, default: card.defaultScale)
                        }
                        // القطر: بتقدر تسحب لبرّا أو لتحت أو للاتنين، والنتيجة
                        // وحدة. ربط التكبير بالعرض لحاله بيخلّي السحب لتحت ما
                        // يعمل إشي، وهاد بيبيّن عطل.
                        let d = (g.translation.width + g.translation.height) / 2
                        store.setScale(resizeBase + d / boardWidth, for: card.id)
                    }
                    .onEnded { _ in
                        resizing = nil
                        store.save()      // الحفظ لما ترفع إيدك، مش كل إطار
                    }
            )
            .accessibilityLabel(lang.s("board.resize"))
    }

    private func move(_ moved: String, before target: String) {
        guard moved != target else { return }
        var ids = store.arrange(cards).map(\.id)
        guard let f = ids.firstIndex(of: moved), let t = ids.firstIndex(of: target)
        else { return }
        ids.move(fromOffsets: IndexSet(integer: f), toOffset: t > f ? t + 1 : t)
        store.setOrder(ids)
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
/// `Layout` مش VStack من HStackات: الأعراض بتتحسب مرّة وحدة من المقاسات المعروفة
/// مسبقًا، بلا قياس ولا تمريرة تانية. هاد اللي بيخلّي السحب سلس — كل إطار
/// بيحرّك مواقع محسوبة، مش بيعيد بناء شجرة.
private struct FlowRows<Content: View>: View {
    let cards: [BoardCard]
    let boardWidth: CGFloat
    let gap: CGFloat
    @ViewBuilder let cell: (BoardCard) -> Content

    var body: some View {
        FlowLayout(gap: gap) {
            ForEach(cards) { card in cell(card) }
        }
        .frame(width: boardWidth)
    }
}

private struct FlowLayout: Layout {
    let gap: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews,
                      cache: inout Void) -> CGSize {
        let maxW = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowH: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > 0 && x + s.width > maxW { x = 0; y += rowH + gap; rowH = 0 }
            x += s.width + gap
            rowH = max(rowH, s.height)
        }
        return CGSize(width: maxW, height: y + rowH)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize,
                       subviews: Subviews, cache: inout Void) {
        var x = bounds.minX, y = bounds.minY, rowH: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > bounds.minX && x + s.width > bounds.maxX {
                x = bounds.minX; y += rowH + gap; rowH = 0
            }
            v.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
            x += s.width + gap
            rowH = max(rowH, s.height)
        }
    }
}

/// السحب لإعادة الترتيب. بينطفي برّا وضع التعديل ووقت التحجيم.
private struct Reorder: ViewModifier {
    let enabled: Bool
    let id: String
    @Binding var dragging: String?
    let onEnter: (String) -> Void

    func body(content: Content) -> some View {
        if enabled {
            content
                .onDrag {
                    dragging = id
                    return NSItemProvider(object: id as NSString)
                }
                .onDrop(of: [.text], delegate: Drop(dragging: $dragging, onEnter: onEnter))
        } else {
            content
        }
    }
}

private struct Drop: DropDelegate {
    @Binding var dragging: String?
    let onEnter: (String) -> Void

    // الترتيب بيصير وقت المرور فوق الهدف مش وقت الإفلات: بتشوف البطاقات بتتزحزح
    // وإنت ماسك، فبتعرف وين رح تقعد قبل ما تفلت.
    func dropEntered(info: DropInfo) {
        if let m = dragging { onEnter(m) }
    }
    func performDrop(info: DropInfo) -> Bool { dragging = nil; return true }
    func dropUpdated(info: DropInfo) -> DropProposal? { DropProposal(operation: .move) }
}
