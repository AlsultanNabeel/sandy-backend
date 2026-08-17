import SwiftUI
import UIKit

/// بطاقة على لوح.
///
/// **المحتوى بيتبنى حسب المقاس، ما بينصغّر.**
///
/// النسخة اللي قبل رسمت البطاقة بعرض كامل وبعدين صغّرتها كصورة. المالك وصف
/// المطلوب بدقّة: بطاقة فيها مفتاح، لما تصغر، بتصير **مفتاح واسمه فوقه وبخط
/// كبير** — تصميم تاني، مش نفس التصميم مصغّر. فالمحتوى بياخد `CardMetrics`
/// وبيقرّر هو.
struct BoardCard: Identifiable, BoardIdentifiable {
    let id: String
    let titleKey: String
    let icon: String
    let defaultSize: CardSize
    /// كم عالي لازم تكون بمقاس `large` — الصغير والوسط بياخدوا ارتفاعهم من
    /// محتواهم.
    let largeHeight: CGFloat
    let content: (CardMetrics) -> AnyView

    var boardID: String { id }

    init<C: View>(_ id: String,
                  titleKey: String,
                  icon: String = "square",
                  defaultSize: CardSize = .medium,
                  largeHeight: CGFloat = 320,
                  @ViewBuilder content: @escaping (CardMetrics) -> C) {
        self.id = id
        self.titleKey = titleKey
        self.icon = icon
        self.defaultSize = defaultSize
        self.largeHeight = largeHeight
        self.content = { m in AnyView(content(m)) }
    }

    /// للبطاقات اللي ما بيفرق معها المقاس.
    init<C: View>(_ id: String,
                  titleKey: String,
                  icon: String = "square",
                  defaultSize: CardSize = .medium,
                  largeHeight: CGFloat = 320,
                  @ViewBuilder content: @escaping () -> C) {
        self.init(id, titleKey: titleKey, icon: icon, defaultSize: defaultSize,
                  largeHeight: largeHeight) { _ in content() }
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

private struct CardFrames: PreferenceKey {
    static var defaultValue: [String: CGRect] = [:]
    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
        value.merge(nextValue()) { _, new in new }
    }
}

private struct BoardWidthKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

/// لوح بطاقات — كل بطاقة بمقاس ودجة، وبأي ترتيب.
///
/// **البطاقة واجهة مستقلة، وهاد سبب إنه السحب بيشتغل.** نسخ سابقة حطّت حالة
/// السحب ع اللوح، واللوح جوّاه `ScrollViewReader`، فكل حركة إصبع كانت تعيد بناء
/// الشجرة — بما فيها الواجهة اللي ماسكة الإيماءة. سويفت‌يو‌آي بتلغي الإيماءة
/// ساعتها، فكانت البطاقة تتحرّك شوي وترجع.
struct CardBoard: View {
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store: BoardStore

    private let cards: [BoardCard]

    @State private var boardWidth: CGFloat =
        UIScreen.main.bounds.width - Theme.Spacing.md * 2
    @State private var frames: [String: CGRect] = [:]
    @State private var dragID: String?
    @State private var edgeTimer: Timer?
    @State private var scroll: ScrollViewProxy?

    init(_ screen: String, @BoardBuilder cards: () -> [BoardCard]) {
        _store = StateObject(wrappedValue: BoardStore(screen))
        self.cards = cards()
    }

    private let gap = Theme.Spacing.md
    private let edgeZone: CGFloat = 110

    private var ordered: [BoardCard] { store.arrange(cards) }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                if store.editing {
                    // ميزة ما حدا بيعرف كيف يستعملها هي ميزة مش موجودة.
                    Text(lang.s("board.hint"))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                        .padding(.horizontal, gap)
                        .padding(.top, Theme.Spacing.sm)
                }

                FlowLayout(gap: gap) {
                    ForEach(ordered) { card in
                        CardCell(card: card,
                                 boardWidth: boardWidth,
                                 store: store,
                                 isHeld: dragID == card.id,
                                 onPick: { dragID = card.id },
                                 onMove: { p in
                                     hover(p, held: card.id)
                                     edgeScroll(at: p, held: card.id)
                                 },
                                 onDrop: {
                                     dragID = nil
                                     stopEdge()
                                     store.setOrder(ordered.map(\.id))
                                 })
                            .id(card.id)
                    }
                }
                .padding(gap)

                Color.clear.frame(height: 96)   // مساحة تحت ساندي العائمة
            }
            .background(
                GeometryReader { g in
                    Color.clear.preference(key: BoardWidthKey.self, value: g.size.width)
                }
            )
            .onPreferenceChange(BoardWidthKey.self) { w in
                let next: CGFloat = w - gap * 2
                if abs(next - boardWidth) > 0.5 { boardWidth = next }
            }
            // بيتبدّل بدخول وضع التعديل وبس — أبدًا بنص إيماءة.
            .scrollDisabled(store.editing)
            .onPreferenceChange(CardFrames.self) { frames = $0 }
            .onAppear { scroll = proxy }
            .onDisappear { stopEdge() }
        }
        .toolbar { ToolbarItem(placement: .topBarTrailing) { editButton } }
    }

    // ── الترتيب ──────────────────────────────────────────────────────────────

    private func hover(_ point: CGPoint, held: String) {
        guard let target = frames.first(where: { $0.value.contains(point) })?.key,
              target != held else { return }
        var ids: [String] = ordered.map(\.id)
        guard let from = ids.firstIndex(of: held),
              let to = ids.firstIndex(of: target) else { return }
        ids.move(fromOffsets: IndexSet(integer: from), toOffset: to > from ? to + 1 : to)
        store.setOrderLive(ids)
    }

    // ── التمرير من الأطراف ───────────────────────────────────────────────────

    private func edgeScroll(at point: CGPoint, held: String) {
        let screenH: CGFloat = UIScreen.main.bounds.height
        let up: Bool = point.y < edgeZone
        let down: Bool = point.y > screenH - edgeZone
        if up || down { startEdge(up: up, held: held) } else { stopEdge() }
    }

    private func startEdge(up: Bool, held: String) {
        guard edgeTimer == nil else { return }
        edgeTimer = Timer.scheduledTimer(withTimeInterval: 0.14, repeats: true) { _ in
            Task { @MainActor in step(up: up, held: held) }
        }
    }

    @MainActor
    private func step(up: Bool, held: String) {
        let ids: [String] = ordered.map(\.id)
        guard let i = ids.firstIndex(of: held) else { return }
        let next: Int = up ? max(0, i - 1) : min(ids.count - 1, i + 1)
        guard next != i, let proxy = scroll else { return }
        withAnimation(.easeInOut(duration: 0.18)) {
            proxy.scrollTo(ids[next], anchor: up ? .top : .bottom)
        }
    }

    private func stopEdge() {
        edgeTimer?.invalidate()
        edgeTimer = nil
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
            } label: {
                Image(systemName: store.editing
                      ? "checkmark.circle.fill" : "slider.horizontal.3")
                    .foregroundColor(Theme.Colors.accent)
            }
            .accessibilityLabel(lang.s(store.editing ? "board.done" : "board.edit"))
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────

/// بطاقة وحدة على اللوح.
///
/// بتملك موقعها وهي بإيدك. هاد شرط عمل مش تنظيم: لو الحالة ع اللوح، كل حركة
/// إصبع بتعيد بناء اللوح كله وبتلغي الإيماءة.
private struct CardCell: View {
    @EnvironmentObject var lang: LanguageManager

    let card: BoardCard
    let boardWidth: CGFloat
    @ObservedObject var store: BoardStore
    let isHeld: Bool
    let onPick: () -> Void
    let onMove: (CGPoint) -> Void
    let onDrop: () -> Void

    @State private var offset: CGSize = .zero

    private var size: CardSize { store.size(card.id, default: card.defaultSize) }

    private var metrics: CardMetrics {
        // ناقص نص الفراغ: بطاقتان صغيرتان جنب بعض لازم يوسعوا السطر مع الفراغ
        // اللي بيناتهن، مش يزيدوا عنه بفراغ كامل.
        let w: CGFloat = size == .small
            ? (boardWidth - Theme.Spacing.md) / 2
            : boardWidth
        return CardMetrics(size: size, width: max(w, 1))
    }

    var body: some View {
        let m: CardMetrics = metrics

        card.content(m)
            .environment(\.cardMetrics, m)
            .frame(width: m.width,
                   height: size == .large ? card.largeHeight : nil,
                   alignment: .topLeading)
            .frame(minHeight: size == .small ? m.width : nil, alignment: .topLeading)
            .clipped()
            .allowsHitTesting(!store.editing)
            .background(
                RoundedRectangle(cornerRadius: Theme.Radius.card)
                    .fill(store.editing ? Theme.Colors.surface.opacity(0.35) : .clear)
            )
            .overlay(alignment: .bottomLeading) { if store.editing { sizeControls } }
            .overlay(alignment: .topLeading) { if store.editing { nameTag } }
            .overlay {
                if store.editing {
                    RoundedRectangle(cornerRadius: Theme.Radius.card)
                        .strokeBorder(Theme.Colors.accent.opacity(0.55),
                                      style: StrokeStyle(lineWidth: 1.5, dash: [5, 4]))
                }
            }
            .background(
                GeometryReader { g in
                    Color.clear.preference(key: CardFrames.self,
                                           value: [card.id: g.frame(in: .global)])
                }
            )
            .scaleEffect(isHeld ? 1.05 : 1)
            .shadow(color: .black.opacity(isHeld ? 0.28 : 0),
                    radius: isHeld ? 14 : 0, y: 6)
            .offset(isHeld ? offset : .zero)
            .zIndex(isHeld ? 1 : 0)
            .contentShape(Rectangle())
            .gesture(reorder, isEnabled: store.editing)
            .animation(.spring(response: 0.3, dampingFraction: 0.85), value: size)
    }

    // ── السحب لإعادة الترتيب ─────────────────────────────────────────────────

    private var reorder: some Gesture {
        DragGesture(minimumDistance: 8, coordinateSpace: .global)
            .onChanged { g in
                if !isHeld {
                    onPick()
                    UIImpactFeedbackGenerator(style: .light).impactOccurred()
                }
                offset = g.translation
                onMove(g.location)
            }
            .onEnded { _ in
                offset = .zero
                onDrop()
            }
    }

    // ── المقاس ───────────────────────────────────────────────────────────────

    /// زرّان. **مش إيماءة، عن قصد.**
    ///
    /// أربع نسخ اعتمدت ع سحب من الزاوية وكل مرّة انلغت الإيماءة لسبب مختلف. الزرّ
    /// ما إله إحداثيات ولا مساحة لمس ولا منافس: بتدوس، بيصير.
    private var sizeControls: some View {
        HStack(spacing: 2) {
            stepButton("minus") { store.setSize(size.previous(), for: card.id) }
            stepButton("plus") { store.setSize(size.next(), for: card.id) }
        }
        .padding(4)
    }

    private func stepButton(_ icon: String, action: @escaping () -> Void) -> some View {
        Button {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.85)) { action() }
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
        } label: {
            Image(systemName: icon)
                .font(.system(size: 13, weight: .bold))
                .foregroundColor(.white)
                .frame(width: 34, height: 34)
                .background(
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .fill(.black.opacity(0.6))
                        .overlay(
                            RoundedRectangle(cornerRadius: 9, style: .continuous)
                                .strokeBorder(.white.opacity(0.3), lineWidth: 0.5))
                )
        }
        .buttonStyle(.plain)
    }

    private var nameTag: some View {
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
}

/// رصف البطاقات بسطور — بطاقة جنب بطاقة لحدّ ما يمتلي السطر.
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
            if x > 0 && x + s.width > maxW + 1 {
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
            if x > bounds.minX && x + s.width > bounds.maxX + 1 {
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
