import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

// ─────────────────────────────────────────────────────────────────────────
//  WidgetDashboard — a per-tab, iPhone-widget-style customizable canvas.
//
//  Two-column grid; every tile has a SHAPE with full control:
//    مربّع (1×1) · عريض (2×1) · طويل (1×2) · كبير (2×2)
//  Enter edit by LONG-PRESSING an empty spot (no prominent button). Then:
//    • drag a tile to reorder (it reflows),
//    • drag the corner handle to resize through the shapes,
//    • tap the − badge to hide it.
//  Layout (order + shape + hidden) persists per tab on device. The OWNER can
//  force-hide any feature centrally (server layer); those never appear.
//  No feature code is removed — this only decides presentation.
// ─────────────────────────────────────────────────────────────────────────

enum WidgetShape: String, Codable, CaseIterable {
    case square, wide, tall, big
    var cols: Int { (self == .wide || self == .big) ? 2 : 1 }
    var rows: Int { (self == .tall || self == .big) ? 2 : 1 }
    static func from(cols: Int, rows: Int) -> WidgetShape {
        switch (min(max(cols, 1), 2), min(max(rows, 1), 2)) {
        case (2, 2): return .big
        case (2, 1): return .wide
        case (1, 2): return .tall
        default:     return .square
        }
    }
}

/// Persisted per-tile state (array order = layout order).
struct DashboardItem: Identifiable, Codable, Equatable {
    let key: String
    var shape: WidgetShape = .square
    var hidden: Bool = false          // hidden BY THE USER
    var id: String { key }
}

/// Static catalog entry — how a feature looks, where it goes, and (optionally)
/// its LIVE mini-content shown when the tile is enlarged. Not persisted.
struct WidgetSpec: Identifiable {
    let key: String
    let icon: String
    let titleKey: String
    let tint: Color
    let destination: () -> AnyView
    /// Interactive preview for bigger shapes (nil = enlarged tile just scales the
    /// icon+title). Gets the current shape so it can show more when there's room.
    var content: ((WidgetShape) -> AnyView)?

    init(key: String, icon: String, titleKey: String, tint: Color,
         content: ((WidgetShape) -> AnyView)? = nil,
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

    /// Normal view: user order, minus owner-hidden and user-hidden.
    var shown: [DashboardItem] {
        items.filter { !serverHidden.contains($0.key) && !$0.hidden }
    }
    /// Edit view: everything the owner allows (user-hidden shown dimmed).
    var editable: [DashboardItem] {
        items.filter { !serverHidden.contains($0.key) }
    }

    // ── mutations (persist) ──────────────────────────────────────────────
    func toggleHidden(_ key: String) {
        guard let i = items.firstIndex(where: { $0.key == key }) else { return }
        items[i].hidden.toggle(); persist()
    }

    func setShape(_ key: String, cols: Int, rows: Int) {
        guard let i = items.firstIndex(where: { $0.key == key }) else { return }
        let s = WidgetShape.from(cols: cols, rows: rows)
        if items[i].shape != s { items[i].shape = s }
    }

    /// Move the dragged key to sit before `target` (live reflow while dragging).
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

    /// First-fit placement into a 2-column grid; tiles may span 2 rows.
    /// Returns each item with its (row, col) and the total row count.
    func placed(_ list: [DashboardItem]) -> (cells: [(item: DashboardItem, row: Int, col: Int)], rows: Int) {
        var occupied = Set<[Int]>()
        func free(_ r: Int, _ c: Int, _ w: Int, _ h: Int) -> Bool {
            for dr in 0..<h { for dc in 0..<w {
                if c + dc >= 2 { return false }
                if occupied.contains([r + dr, c + dc]) { return false }
            } }
            return true
        }
        var cells: [(DashboardItem, Int, Int)] = []
        var maxRow = 0
        for it in list {
            let w = it.shape.cols, h = it.shape.rows
            var r = 0
            while true {
                var placedHere = false
                for c in 0...(2 - w) where free(r, c, w, h) {
                    for dr in 0..<h { for dc in 0..<w { occupied.insert([r + dr, c + dc]) } }
                    cells.append((it, r, c))
                    maxRow = max(maxRow, r + h)
                    placedHere = true
                    break
                }
                if placedHere { break }
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

    /// Cell side from the screen width — two columns with one gap, page padding.
    private var cell: CGFloat {
        (UIScreen.main.bounds.width - gap * 3) / 2
    }

    var body: some View {
        let list = store.editing ? store.editable : store.shown
        let layout = store.placed(list)
        let contentH = layout.rows > 0
            ? CGFloat(layout.rows) * cell + CGFloat(layout.rows - 1) * gap : cell

        ScrollView {
            ZStack(alignment: .topLeading) {
                // Empty backdrop: long-press to toggle edit mode (no loud button).
                Color.clear
                    .frame(width: cell * 2 + gap, height: contentH)
                    .contentShape(Rectangle())
                    .onLongPressGesture(minimumDuration: 0.5) {
                        withAnimation { store.editing.toggle() }
                        if !store.editing { store.persist() }
                    }

                ForEach(layout.cells, id: \.item.id) { entry in
                    tile(entry.item)
                        .frame(width: span(entry.item.shape.cols),
                               height: span(entry.item.shape.rows))
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
        .overlay(alignment: .bottom) {
            if store.editing {
                Text(lang.s("widgets.hint"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .padding(.horizontal, Theme.Spacing.md)
                    .padding(.vertical, Theme.Spacing.sm)
                    .background(.ultraThinMaterial, in: Capsule())
                    .padding(.bottom, Theme.Spacing.lg)
            }
        }
    }

    private func span(_ n: Int) -> CGFloat { CGFloat(n) * cell + CGFloat(n - 1) * gap }

    @ViewBuilder
    private func tile(_ item: DashboardItem) -> some View {
        if let spec = store.spec(item.key) {
            if store.editing {
                WidgetCard(spec: spec, shape: item.shape, lang: lang)
                    .opacity(item.hidden ? 0.35 : 1)
                    .overlay(alignment: .topLeading) { hideBadge(item) }
                    .overlay(alignment: .bottomTrailing) { resizeHandle(item) }
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
            } else if item.shape != .square, let content = spec.content {
                // Enlarged + has live content: a header that opens the full
                // screen, then the interactive mini-view you can act on in place.
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    NavigationLink { spec.destination() } label: { contentHeader(spec) }
                        .buttonStyle(.plain)
                    content(item.shape)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                }
                .padding(Theme.Spacing.md)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .liquidGlass(cornerRadius: Theme.Radius.card)
            } else {
                NavigationLink { spec.destination() } label: {
                    WidgetCard(spec: spec, shape: item.shape, lang: lang)
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

    // Drag the corner to resize through the shapes (relative to the shape the
    // gesture started on, so it doesn't compound).
    private func resizeHandle(_ item: DashboardItem) -> some View {
        Image(systemName: "arrow.up.left.and.arrow.down.right.circle.fill")
            .font(.system(size: 22))
            .foregroundColor(Theme.Colors.accent)
            .background(Circle().fill(Theme.Colors.card))
            .offset(x: 6, y: 6)
            .gesture(
                DragGesture()
                    .onChanged { v in
                        if resizeStart?.key != item.key {
                            resizeStart = (item.key, item.shape.cols, item.shape.rows)
                        }
                        guard let base = resizeStart else { return }
                        let stepW = Int((v.translation.width / (cell * 0.55)).rounded())
                        let stepH = Int((v.translation.height / (cell * 0.55)).rounded())
                        store.setShape(item.key, cols: base.cols + stepW, rows: base.rows + stepH)
                    }
                    .onEnded { _ in
                        resizeStart = nil
                        store.persist()
                    }
            )
    }
}

/// One tile's face — icon + title, sized to its shape. Larger shapes show more.
private struct WidgetCard: View {
    let spec: WidgetSpec
    let shape: WidgetShape
    let lang: LanguageManager

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Image(systemName: spec.icon)
                .font(.system(size: shape.rows == 2 ? 30 : 22, weight: .semibold))
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
        dragging = nil
        store.persist()
        return true
    }
}
