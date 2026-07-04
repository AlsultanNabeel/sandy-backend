import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

// ─────────────────────────────────────────────────────────────────────────
//  WidgetDashboard — a per-tab, iPhone-widget-style customizable canvas.
//
//  Two-column grid. Every tile has a FREE size: width 1–2 columns, height 1–4
//  rows — so you can make it square, wide, tall, or as big as you want.
//  Enter edit by LONG-PRESSING an empty spot. Then:
//    • drag a tile to reorder (it reflows),
//    • grab the bottom-corner grip and drag out/in to grow/shrink,
//    • tap the − badge to hide it.
//  Enlarged tiles show LIVE, interactive feature content that fills the space.
//  Layout persists per tab on device; the OWNER can force-hide any feature
//  centrally. No feature code is removed — this only decides presentation.
// ─────────────────────────────────────────────────────────────────────────

private let kMaxCols = 2
private let kMaxRows = 4

/// Persisted per-tile state (array order = layout order).
struct DashboardItem: Identifiable, Codable, Equatable {
    let key: String
    var cols: Int = 1
    var rows: Int = 1
    var hidden: Bool = false          // hidden BY THE USER
    var id: String { key }
    var isBig: Bool { cols > 1 || rows > 1 }
}

/// Static catalog entry — how a feature looks, where it goes, and (optionally)
/// its LIVE mini-content shown when the tile is enlarged. Not persisted.
struct WidgetSpec: Identifiable {
    let key: String
    let icon: String
    let titleKey: String
    let tint: Color
    let destination: () -> AnyView
    /// Interactive preview for enlarged tiles (nil = just a bigger icon+title).
    /// It self-measures and fills whatever space the tile gives it.
    var content: (() -> AnyView)?

    init(key: String, icon: String, titleKey: String, tint: Color,
         content: (() -> AnyView)? = nil,
         destination: @escaping () -> AnyView) {
        self.key = key; self.icon = icon; self.titleKey = titleKey
        self.tint = tint; self.content = content; self.destination = destination
    }
    var id: String { key }
}

@MainActor
final class DashboardStore: ObservableObject {
    @Published var items: [DashboardItem] = []
    @Published var editing = false
    @Published var serverHidden: Set<String> = []

    private let storageKey: String
    let catalog: [WidgetSpec]

    init(id: String, catalog: [WidgetSpec]) {
        self.storageKey = "dashboard.\(id)"
        self.catalog = catalog
        load()
    }

    func spec(_ key: String) -> WidgetSpec? { catalog.first { $0.key == key } }
    func applyServerHidden(_ hidden: Set<String>) { serverHidden = hidden }

    var shown: [DashboardItem] {
        items.filter { !serverHidden.contains($0.key) && !$0.hidden }
    }
    var editable: [DashboardItem] {
        items.filter { !serverHidden.contains($0.key) }
    }

    // ── mutations (persist) ──────────────────────────────────────────────
    func toggleHidden(_ key: String) {
        guard let i = items.firstIndex(where: { $0.key == key }) else { return }
        items[i].hidden.toggle(); persist()
    }

    /// Grow/shrink freely, clamped to the grid (cols 1–2, rows 1–4).
    func setSize(_ key: String, cols: Int, rows: Int) {
        guard let i = items.firstIndex(where: { $0.key == key }) else { return }
        let c = min(max(cols, 1), kMaxCols)
        let r = min(max(rows, 1), kMaxRows)
        if items[i].cols != c || items[i].rows != r {
            items[i].cols = c; items[i].rows = r
        }
    }

    func relocate(_ dragged: String, before target: String) {
        guard dragged != target,
              let from = items.firstIndex(where: { $0.key == dragged }) else { return }
        let item = items.remove(at: from)
        let insertAt = items.firstIndex(where: { $0.key == target }) ?? items.count
        items.insert(item, at: insertAt)
    }

    func persist() {
        if let data = try? JSONEncoder().encode(items) {
            UserDefaults.standard.set(data, forKey: storageKey)
        }
    }

    private func load() {
        let saved = UserDefaults.standard.data(forKey: storageKey)
            .flatMap { try? JSONDecoder().decode([DashboardItem].self, from: $0) } ?? []
        var merged = saved.filter { spec($0.key) != nil }
        let present = Set(merged.map(\.key))
        for s in catalog where !present.contains(s.key) {
            merged.append(DashboardItem(key: s.key))
        }
        items = merged
    }

    /// First-fit placement into a 2-column grid; tiles may span rows/cols.
    func placed(_ list: [DashboardItem]) -> (cells: [(item: DashboardItem, row: Int, col: Int)], rows: Int) {
        var occupied = Set<[Int]>()
        func free(_ r: Int, _ c: Int, _ w: Int, _ h: Int) -> Bool {
            for dr in 0..<h { for dc in 0..<w {
                if c + dc >= kMaxCols { return false }
                if occupied.contains([r + dr, c + dc]) { return false }
            } }
            return true
        }
        var cells: [(DashboardItem, Int, Int)] = []
        var maxRow = 0
        for it in list {
            let w = min(it.cols, kMaxCols), h = min(it.rows, kMaxRows)
            var r = 0
            while true {
                var done = false
                for c in 0...(kMaxCols - w) where free(r, c, w, h) {
                    for dr in 0..<h { for dc in 0..<w { occupied.insert([r + dr, c + dc]) } }
                    cells.append((it, r, c)); maxRow = max(maxRow, r + h); done = true; break
                }
                if done { break }
                r += 1
            }
        }
        return (cells, maxRow)
    }
}

// MARK: - The canvas

struct WidgetDashboard: View {
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var store: DashboardStore
    @State private var dragging: String?
    @State private var resizeStart: (key: String, cols: Int, rows: Int)?

    private let gap = Theme.Spacing.md
    private var cell: CGFloat { (UIScreen.main.bounds.width - gap * 3) / 2 }
    private func span(_ n: Int) -> CGFloat { CGFloat(n) * cell + CGFloat(n - 1) * gap }

    var body: some View {
        let list = store.editing ? store.editable : store.shown
        let layout = store.placed(list)
        let contentH = layout.rows > 0
            ? CGFloat(layout.rows) * cell + CGFloat(layout.rows - 1) * gap : cell

        ScrollView {
            ZStack(alignment: .topLeading) {
                Color.clear
                    .frame(width: cell * 2 + gap, height: contentH)
                    .contentShape(Rectangle())
                    .onLongPressGesture(minimumDuration: 0.5) {
                        withAnimation { store.editing.toggle() }
                        if !store.editing { store.persist() }
                    }

                ForEach(layout.cells, id: \.item.id) { entry in
                    tile(entry.item)
                        .frame(width: span(min(entry.item.cols, kMaxCols)),
                               height: span(min(entry.item.rows, kMaxRows)))
                        .offset(x: CGFloat(entry.col) * (cell + gap),
                                y: CGFloat(entry.row) * (cell + gap))
                }
            }
            .frame(width: cell * 2 + gap, height: contentH, alignment: .topLeading)
            .padding(gap)
            .animation(.spring(response: 0.35, dampingFraction: 0.82), value: store.items)
        }
        .toolbar {
            if store.editing {
                ToolbarItem(placement: .primaryAction) {
                    Button(lang.s("common.done")) {
                        withAnimation { store.editing = false }
                        store.persist()
                    }
                }
            }
        }
        .overlay(alignment: .bottom) { if store.editing { hintBar } }
    }

    private var hintBar: some View {
        Text(lang.s("widgets.hint"))
            .font(Theme.Typography.caption)
            .foregroundColor(Theme.Colors.secondaryText)
            .padding(.horizontal, Theme.Spacing.md)
            .padding(.vertical, Theme.Spacing.sm)
            .background(.ultraThinMaterial, in: Capsule())
            .padding(.bottom, Theme.Spacing.lg)
    }

    @ViewBuilder
    private func tile(_ item: DashboardItem) -> some View {
        if let spec = store.spec(item.key) {
            if store.editing {
                WidgetCard(spec: spec, big: item.isBig, lang: lang)
                    .opacity(item.hidden ? 0.35 : 1)
                    .overlay(alignment: .topLeading) { hideBadge(item) }
                    .overlay(alignment: .bottomTrailing) { resizeGrip(item) }
                    .rotationEffect(.degrees(1))
                    .animation(.easeInOut(duration: 0.14).repeatForever(autoreverses: true),
                               value: store.editing)
                    .onDrag {
                        dragging = item.key
                        return NSItemProvider(object: item.key as NSString)
                    }
                    .onDrop(of: [UTType.text],
                            delegate: WidgetDropDelegate(target: item.key, store: store,
                                                         dragging: $dragging))
            } else if item.isBig, let content = spec.content {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    NavigationLink { spec.destination() } label: { contentHeader(spec) }
                        .buttonStyle(.plain)
                    content()
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                }
                .padding(Theme.Spacing.md)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .liquidGlass(cornerRadius: Theme.Radius.card)
            } else {
                NavigationLink { spec.destination() } label: {
                    WidgetCard(spec: spec, big: item.isBig, lang: lang)
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func contentHeader(_ spec: WidgetSpec) -> some View {
        HStack(spacing: Theme.Spacing.sm) {
            Image(systemName: spec.icon)
                .font(.system(size: 16, weight: .semibold))
                .foregroundColor(spec.tint)
            Text(lang.s(spec.titleKey))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
            Spacer(minLength: 0)
            Image(systemName: "chevron.left")
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(Theme.Colors.tertiaryText)
        }
    }

    private func hideBadge(_ item: DashboardItem) -> some View {
        Button { store.toggleHidden(item.key) } label: {
            Image(systemName: item.hidden ? "plus.circle.fill" : "minus.circle.fill")
                .font(.system(size: 22))
                .foregroundColor(item.hidden ? Theme.Colors.success : Theme.Colors.warn)
                .background(Circle().fill(Theme.Colors.card))
        }
        .buttonStyle(.plain)
        .offset(x: -6, y: -6)
    }

    // A real corner grip: drag out to grow, in to shrink (both axes), relative to
    // the size the drag started on so it doesn't compound.
    private func resizeGrip(_ item: DashboardItem) -> some View {
        Image(systemName: "arrow.down.right")
            .font(.system(size: 12, weight: .heavy))
            .foregroundColor(Theme.Colors.onAccent)
            .frame(width: 28, height: 28)
            .background(Circle().fill(Theme.Colors.accent))
            .offset(x: 8, y: 8)
            .gesture(
                DragGesture()
                    .onChanged { v in
                        if resizeStart?.key != item.key {
                            resizeStart = (item.key, item.cols, item.rows)
                        }
                        guard let base = resizeStart else { return }
                        let dc = Int((v.translation.width / (cell * 0.5)).rounded())
                        let dr = Int((v.translation.height / (cell * 0.5)).rounded())
                        store.setSize(item.key, cols: base.cols + dc, rows: base.rows + dr)
                    }
                    .onEnded { _ in resizeStart = nil; store.persist() }
            )
    }
}

/// Compact tile face — icon + title, used for 1×1 tiles and while editing.
private struct WidgetCard: View {
    let spec: WidgetSpec
    let big: Bool
    let lang: LanguageManager

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Image(systemName: spec.icon)
                .font(.system(size: big ? 28 : 22, weight: .semibold))
                .foregroundColor(spec.tint)
            Spacer(minLength: 0)
            Text(lang.s(spec.titleKey))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(Theme.Spacing.md)
        .liquidGlass(cornerRadius: Theme.Radius.card)
    }
}

/// Live reflow while dragging a tile over another.
private struct WidgetDropDelegate: DropDelegate {
    let target: String
    let store: DashboardStore
    @Binding var dragging: String?

    func dropEntered(info: DropInfo) {
        guard let dragging, dragging != target else { return }
        withAnimation(.spring(response: 0.3, dampingFraction: 0.82)) {
            store.relocate(dragging, before: target)
        }
    }
    func dropUpdated(info: DropInfo) -> DropProposal? { DropProposal(operation: .move) }
    func performDrop(info: DropInfo) -> Bool {
        dragging = nil; store.persist(); return true
    }
}
