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

/// لوح بطاقات — كل بطاقة بأي حجم، وبأي ترتيب.
///
/// **البطاقة واجهة مستقلة، وهاد السبب الوحيد إنه السحب بيشتغل.**
///
/// أول نسختين حطّوا حالة السحب والتحجيم ع اللوح نفسه. اللوح جوّاه
/// `ScrollViewReader` وكان جوّاه `GeometryReader`، فكل حركة إصبع كانت تحدّث حالة
/// اللوح، واللوح يعيد بناء الشجرة كلها — **بما فيها الواجهة اللي ماسكة
/// الإيماءة**. سويفت‌يو‌آي بتلغي الإيماءة لما تنبني واجهتها من جديد، فكانت
/// البطاقة تصغّر شوي وتنقطع وترجع. المالك وصفها بالحرف: «بصغّر شوييية وبرجع
/// بكبر، بثبتش».
///
/// هلق البطاقة بتملك حجمها وهي بإيدك (`live`) وما بتحكي مع المخزن إلا لما ترفع
/// إيدك. يعني إعادة الرسم محصورة ببطاقة وحدة، واللوح ما بينهزّ، والإيماءة بتعيش.
///
/// **والترتيب زي شاشة الآيفون مش زي `onDrag`.** `onDrag`/`onDrop` آلية نقل بين
/// التطبيقات: بدها ضغطة طويلة، بتعمل صورة شبح، وبتتخانق مع التمرير. هون:
/// البطاقة بتمشي مع إصبعك، وموقعك بيتقارن بمواقع الباقي فبيتغيّر الترتيب وإنت
/// لسا ماسك.
struct CardBoard: View {
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store: BoardStore

    private let cards: [BoardCard]

    // بيبدأ بعرض الشاشة مش صفر: التفضيل بيوصل بعد أول رسمة، وبطاقات بعرض صفر
    // بأول إطار بتومض ومرّات بتخلّي الرصف يبدأ غلط.
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
    /// كم قريب من طرف الشاشة لازم توصل حتى تمشي معك.
    private let edgeZone: CGFloat = 110

    private var ordered: [BoardCard] { store.arrange(cards) }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                // شريط إرشاد بوضع التعديل.
                //
                // ميزة ما حدا بيعرف كيف يستعملها هي ميزة مش موجودة. المالك كان
                // بيدوّر ع طريقة يمسك فيها البطاقة وما لقي، والشاشة ما كانت
                // بتقول إشي — فبدا شكله عطل.
                if store.editing {
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
            // العرض بينقرا مرّة عبر تفضيل، مش بـ GeometryReader بيلفّ كل شي:
            // اللافّة كانت تعيد بناء الـ ScrollView مع كل تغيير حالة.
            .background(
                GeometryReader { g in
                    Color.clear.preference(key: BoardWidthKey.self, value: g.size.width)
                }
            )
            .onPreferenceChange(BoardWidthKey.self) { w in
                let next: CGFloat = w - gap * 2
                if abs(next - boardWidth) > 0.5 { boardWidth = next }
            }
            // بيتبدّل بدخول وضع التعديل وبس — أبدًا بنص إيماءة. أي تغيير
            // بإعدادات الـ ScrollView وإيدك نازلة بيلغي الإيماءة.
            .scrollDisabled(store.editing)
            .onPreferenceChange(CardFrames.self) { frames = $0 }
            .onAppear { scroll = proxy }
            .onDisappear { stopEdge() }
        }
        .toolbar { ToolbarItem(placement: .topBarTrailing) { editButton } }
    }

    // ── الترتيب ──────────────────────────────────────────────────────────────

    /// البطاقة اللي تحت إصبعك بتفسح، وقت ما تمرق فوقها — مش وقت ما تفلت.
    private func hover(_ point: CGPoint, held: String) {
        guard let target = frames.first(where: { $0.value.contains(point) })?.key,
              target != held else { return }
        var ids: [String] = ordered.map(\.id)
        guard let from = ids.firstIndex(of: held),
              let to = ids.firstIndex(of: target) else { return }
        ids.move(fromOffsets: IndexSet(integer: from), toOffset: to > from ? to + 1 : to)
        store.setOrderLive(ids)      // الحفظ لما ترفع إيدك
    }

    // ── التمرير من الأطراف ───────────────────────────────────────────────────

    private func edgeScroll(at point: CGPoint, held: String) {
        let screenH: CGFloat = UIScreen.main.bounds.height
        let up: Bool = point.y < edgeZone
        let down: Bool = point.y > screenH - edgeZone
        if up || down {
            startEdge(up: up, held: held)
        } else {
            stopEdge()
        }
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

    // ── زر التعديل ───────────────────────────────────────────────────────────

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
/// بتملك حجمها وموقعها وهي بإيدك. هاد مش تنظيم — هاد شرط عمل: لو الحالة ع
/// اللوح، كل حركة إصبع بتعيد بناء اللوح كله وبتلغي الإيماءة اللي بإيدك.
private struct CardCell: View {
    @EnvironmentObject var lang: LanguageManager

    let card: BoardCard
    let boardWidth: CGFloat
    @ObservedObject var store: BoardStore
    let isHeld: Bool
    let onPick: () -> Void
    let onMove: (CGPoint) -> Void
    let onDrop: () -> Void

    /// الحجم وهو بإيدك. `nil` يعني «خُذه من المخزن».
    @State private var live: Double?
    @State private var base: Double = 1
    @State private var offset: CGSize = .zero

    private var scale: Double {
        live ?? store.scale(card.id, default: card.defaultScale)
    }

    var body: some View {
        let w: CGFloat = boardWidth * scale
        let h: CGFloat = card.designHeight * scale

        card.content
            .frame(width: max(boardWidth, 1), height: card.designHeight,
                   alignment: .topLeading)
            .clipped()
            .scaleEffect(scale, anchor: .topLeading)
            .frame(width: max(w, 1), height: max(h, 1), alignment: .topLeading)
            .allowsHitTesting(!store.editing)
            .background(
                RoundedRectangle(cornerRadius: Theme.Radius.card)
                    .fill(store.editing ? Theme.Colors.surface.opacity(0.35) : .clear)
            )
            .overlay(alignment: .topLeading) { if store.editing { nameTag } }
            .overlay(alignment: .bottomLeading) { if store.editing { sizeControls } }
            .overlay(alignment: .bottomTrailing) { if store.editing { cornerHandle } }
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
            // القرص بإصبعين — إيماءة ما بتزاحم التمرير أصلًا لأنها بإصبعين،
            // فهي أضمن إيماءة تحجيم موجودة. زيادة ع الزرّين، مش بدلهم.
            .gesture(pinch, isEnabled: store.editing)
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

    // ── التحجيم ──────────────────────────────────────────────────────────────

    private var pinch: some Gesture {
        MagnifyGesture()
            .onChanged { g in
                if live == nil {
                    base = store.scale(card.id, default: card.defaultScale)
                }
                let want: Double = base * g.magnification
                live = min(max(want, BoardStore.minScale), BoardStore.maxScale)
            }
            .onEnded { _ in
                if let v = live { store.setScale(v, for: card.id) }
                live = nil
            }
    }

    /// أدوات الحجم — زرّان وزاوية.
    ///
    /// **الزرّان أساس، مش احتياط.**
    ///
    /// أربع نسخ متتالية اعتمدت ع إيماءة سحب وحدها، وكل مرّة كانت تنلغي لسبب
    /// مختلف — إعادة بناء الشجرة، تبديل إعداد بالتمرير، هدف لمس برّا الإطار.
    /// وكل مرّة كنت بشيل سبب واحد وبيطلع غيره، لأني بحلّل سلوك ما بقدر أشوفه.
    ///
    /// الزرّ ما بينلغى. ما إله إحداثيات ولا مساحة لمس ولا منافسة مع إيماءة تانية:
    /// بتدوس، بيصير. فالتحكّم الأكيد صار زرّين، والسحب من الزاوية والقرص ضلّوا
    /// فوقهم للي بيحبّهم — الميزة ما بتوقف عليهم.
    ///
    /// وخطوة عشرة بالمية: صغيرة كفاية تظبّط، وكبيرة كفاية تحسّها من ضغطة وحدة.
    private var sizeControls: some View {
        HStack(spacing: 2) {
            stepButton("minus", by: -0.10)
            stepButton("plus", by: 0.10)
        }
        .padding(4)
    }

    private func stepButton(_ icon: String, by delta: Double) -> some View {
        Button {
            let now: Double = store.scale(card.id, default: card.defaultScale)
            store.setScale(now + delta, for: card.id)
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

    /// الزاوية الغامقة — شكل أبل، وبتسحب كمان.
    ///
    /// موجودة لأنها الشكل اللي بيقول «هاي البطاقة بتتحجّم» بلا كلام: هي حرفيًا
    /// زاوية البطاقة. والسحب منها بيشتغل، بس مش هو الضمان — الضمان الزرّان
    /// جنبها. لو انلغت الإيماءة لأي سبب، الميزة بتضل شغّالة.
    private var cornerHandle: some View {
        ZStack {
            Color.clear
            CornerGrip()
        }
        .frame(width: 44, height: 44)      // أقل هدف لمس بتوصي فيه أبل
        .contentShape(Rectangle())
        .highPriorityGesture(
            DragGesture(minimumDistance: 0, coordinateSpace: .global)
                .onChanged { g in
                    if live == nil {
                        base = store.scale(card.id, default: card.defaultScale)
                    }
                    let d: CGFloat = (g.translation.width + g.translation.height) / 2
                    let want: Double = base + Double(d / max(boardWidth, 1))
                    live = min(max(want, BoardStore.minScale), BoardStore.maxScale)
                }
                .onEnded { _ in
                    if let v = live { store.setScale(v, for: card.id) }
                    live = nil
                }
        )
        .accessibilityLabel(lang.s("board.resize"))
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

// ─────────────────────────────────────────────────────────────────────────────

/// مقبض التحجيم — زاوية غامقة، زي نظام أبل.
///
/// كان سهمًا داخل دائرة ملوّنة. السهم بيقول «اسحبني» بالكلام، والزاوية بتقولها
/// بالشكل: هي حرفيًا زاوية البطاقة. وغامق مش ملوّن عن قصد — اللون بيسحب العين
/// لعنصر تحكّم المفروض يستنّى دورك.
private struct CornerGrip: View {
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(.ultraThinMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(.black.opacity(0.45))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(.white.opacity(0.35), lineWidth: 0.5)
                )
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            CornerBracket()
                .stroke(.white.opacity(0.95),
                        style: StrokeStyle(lineWidth: 2, lineCap: .round,
                                           lineJoin: .round))
                .frame(width: 11, height: 11)
        }
        .frame(width: 26, height: 26)
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
