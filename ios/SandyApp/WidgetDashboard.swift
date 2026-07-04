import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

// ─────────────────────────────────────────────────────────────────────────
//  WidgetDashboard — a per-tab board that behaves like the iPhone Home Screen.
//
//  Faithful to iOS (researched, not guessed):
//    • Long-press an empty spot → edit mode (tiles jiggle).
//    • A + button opens the WIDGET GALLERY of everything not on the board;
//      pick one and a FIXED size (small 1×1 · medium 2×1 · large 2×2) to add.
//    • A − badge removes a tile (it goes back to the gallery).
//    • Drag a tile to reorder; the rest reflow.
//    • Tap a jiggling tile to select it, then choose its size from the bottom
//      bar (iOS changes size by re-adding; a size bar is the friendly equivalent).
//  Bigger sizes show denser LIVE content. Layout persists per tab on device.
//  The OWNER can force-hide any feature centrally (it never reaches the gallery).
//  No feature code is removed — this only decides presentation.
// ─────────────────────────────────────────────────────────────────────────

enum WidgetSize: String, Codable, CaseIterable {
    case small, medium, large
    var cols: Int { self == .small ? 1 : 2 }
    var rows: Int { self == .large ? 2 : 1 }
    var labelKey: String { "widgets.size.\(rawValue)" }
}

/// Persisted per-tile state (array order = layout order). `hidden` == in gallery.
struct DashboardItem: Identifiable, Codable, Equatable {
    let key: String
    var size: WidgetSize = .small
    var hidden: Bool = false
    var id: String { key }
    var isBig: Bool { size != .small }
}

/// Static catalog entry — how a feature looks, where it goes, and (optionally)
/// its LIVE mini-content shown when the tile is enlarged. Not persisted.
struct WidgetSpec: Identifiable {
    let key: String
    let icon: String
    let titleKey: String
    let tint: Color
    let destination: () -> AnyView
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

    /// On the board: owner-allowed and not sent to the gallery.
    var shown: [DashboardItem] {
        items.filter { !serverHidden.contains($0.key) && !$0.hidden }
    }
    /// In the + gallery: owner-allowed but currently removed.
    var gallery: [DashboardItem] {
        items.filter { !serverHidden.contains($0.key) && $0.hidden }
    }

    // ── mutations (persist) ──────────────────────────────────────────────
    func remove(_ key: String) { setHidden(key, true) }

    func add(_ key: String, size: WidgetSize = .medium) {
        guard let i = items.firstIndex(where: { $0.key == key }) else { return }
        items[i].hidden = false
        items[i].size = size
        persist()
    }

    private func setHidden(_ key: String, _ hidden: Bool) {
        guard let i = items.firstIndex(where: { $0.key == key }) else { return }
        items[i].hidden = hidden; persist()
    }

    func setSize(_ key: String, _ size: WidgetSize) {
        guard let i = items.firstIndex(where: { $0.key == key }) else { return }
        if items[i].size != size { items[i].size = size; persist() }
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

    /// First-fit placement into a 2-column grid; medium spans 2 cols, large 2×2.
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
            let w = it.size.cols, h = it.size.rows
            var r = 0
            while true {
                var done = false
                for c in 0...(2 - w) where free(r, c, w, h) {
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

// MARK: - The board

struct WidgetDashboard: View {
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var store: DashboardStore
    @State private var dragging: String?
    @State private var selected: String?
    @State private var showGallery = false

    private let gap = Theme.Spacing.md
    private var cell: CGFloat { (UIScreen.main.bounds.width - gap * 3) / 2 }
    private func span(_ n: Int) -> CGFloat { CGFloat(n) * cell + CGFloat(n - 1) * gap }

    var body: some View {
        let layout = store.placed(store.shown)
        let contentH = layout.rows > 0
            ? CGFloat(layout.rows) * cell + CGFloat(layout.rows - 1) * gap : cell

        ScrollView {
            ZStack(alignment: .topLeading) {
                Color.clear
                    .frame(width: cell * 2 + gap, height: contentH)
                    .contentShape(Rectangle())
                    .onLongPressGesture(minimumDuration: 0.5) { enterEdit() }

                ForEach(layout.cells, id: \.item.id) { entry in
                    tile(entry.item)
                        .frame(width: span(entry.item.size.cols),
                               height: span(entry.item.size.rows))
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
                ToolbarItem(placement: .navigationBarLeading) {
                    Button { showGallery = true } label: { Image(systemName: "plus") }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button(lang.s("common.done")) { exitEdit() }
                }
            }
        }
        .overlay(alignment: .bottom) { if store.editing, let key = selected { sizeBar(key) } }
        .sheet(isPresented: $showGallery) {
            WidgetGallery(store: store).environmentObject(lang)
        }
    }

    private func enterEdit() { withAnimation { store.editing = true } }
    private func exitEdit() { withAnimation { store.editing = false }; selected = nil; store.persist() }

    // Bottom size selector for the selected tile (iOS-style size choice).
    private func sizeBar(_ key: String) -> some View {
        let current = store.items.first { $0.key == key }?.size ?? .small
        return HStack(spacing: Theme.Spacing.sm) {
            ForEach(WidgetSize.allCases, id: \.self) { size in
                Button { store.setSize(key, size) } label: {
                    Text(lang.s(size.labelKey))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(current == size ? Theme.Colors.onAccent : Theme.Colors.primaryText)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.vertical, Theme.Spacing.sm)
                        .background(current == size ? Theme.Colors.accent : Color.clear,
                                    in: Capsule())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(Theme.Spacing.xs)
        .background(.ultraThinMaterial, in: Capsule())
        .padding(.bottom, Theme.Spacing.lg)
    }

    @ViewBuilder
    private func tile(_ item: DashboardItem) -> some View {
        if let spec = store.spec(item.key) {
            if store.editing {
                Group {
                    if item.isBig, let content = spec.content {
                        contentTile(spec, content: content, interactive: false)
                    } else {
                        WidgetCard(spec: spec, big: item.isBig, lang: lang)
                    }
                }
                .overlay(alignment: .topLeading) { removeBadge(item) }
                .overlay(selected == item.key ? RoundedRectangle(cornerRadius: Theme.Radius.card)
                    .stroke(Theme.Colors.accent, lineWidth: 2) : nil)
                .rotationEffect(.degrees(1))
                .animation(.easeInOut(duration: 0.14).repeatForever(autoreverses: true), value: store.editing)
                .onTapGesture { selected = (selected == item.key) ? nil : item.key }
                .onDrag { dragging = item.key; return NSItemProvider(object: item.key as NSString) }
                .onDrop(of: [UTType.text],
                        delegate: WidgetDropDelegate(target: item.key, store: store, dragging: $dragging))
            } else if item.isBig, let content = spec.content {
                contentTile(spec, content: content, interactive: true)
            } else {
                NavigationLink { spec.destination() } label: {
                    WidgetCard(spec: spec, big: item.isBig, lang: lang)
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func contentTile(_ spec: WidgetSpec, content: @escaping () -> AnyView,
                             interactive: Bool) -> some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            if interactive {
                NavigationLink { spec.destination() } label: { contentHeader(spec) }
                    .buttonStyle(.plain)
            } else {
                contentHeader(spec)
            }
            content()
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .allowsHitTesting(interactive)
        }
        .padding(Theme.Spacing.md)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .liquidGlass(cornerRadius: Theme.Radius.card)
    }

    private func contentHeader(_ spec: WidgetSpec) -> some View {
        HStack(spacing: Theme.Spacing.sm) {
            Image(systemName: spec.icon)
                .font(.system(size: 16, weight: .semibold)).foregroundColor(spec.tint)
            Text(lang.s(spec.titleKey))
                .font(Theme.Typography.headline).foregroundColor(Theme.Colors.primaryText)
            Spacer(minLength: 0)
            Image(systemName: "chevron.left")
                .font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.Colors.tertiaryText)
        }
    }

    private func removeBadge(_ item: DashboardItem) -> some View {
        Button { store.remove(item.key); if selected == item.key { selected = nil } } label: {
            Image(systemName: "minus.circle.fill")
                .font(.system(size: 22)).foregroundColor(Theme.Colors.warn)
                .background(Circle().fill(Theme.Colors.card))
        }
        .buttonStyle(.plain)
        .offset(x: -6, y: -6)
    }
}

/// Compact tile face — icon + title (1×1 tiles and while editing small ones).
private struct WidgetCard: View {
    let spec: WidgetSpec
    let big: Bool
    let lang: LanguageManager

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Image(systemName: spec.icon)
                .font(.system(size: big ? 28 : 22, weight: .semibold)).foregroundColor(spec.tint)
            Spacer(minLength: 0)
            Text(lang.s(spec.titleKey))
                .font(Theme.Typography.headline).foregroundColor(Theme.Colors.primaryText).lineLimit(2)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(Theme.Spacing.md)
        .liquidGlass(cornerRadius: Theme.Radius.card)
    }
}

/// The + gallery: everything currently off the board, tap to add.
private struct WidgetGallery: View {
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var store: DashboardStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                SandyBackground()
                ScrollView {
                    VStack(spacing: Theme.Spacing.md) {
                        if store.gallery.isEmpty {
                            Text(lang.s("widgets.gallery.empty"))
                                .font(Theme.Typography.subheadline)
                                .foregroundColor(Theme.Colors.secondaryText)
                                .padding(.top, Theme.Spacing.xl)
                        }
                        ForEach(store.gallery) { item in
                            if let spec = store.spec(item.key) {
                                Button { store.add(item.key); dismiss() } label: {
                                    HStack(spacing: Theme.Spacing.md) {
                                        Image(systemName: spec.icon).foregroundColor(spec.tint).frame(width: 28)
                                        Text(lang.s(spec.titleKey))
                                            .font(Theme.Typography.headline)
                                            .foregroundColor(Theme.Colors.primaryText)
                                        Spacer(minLength: 0)
                                        Image(systemName: "plus.circle.fill").foregroundColor(Theme.Colors.accent)
                                    }
                                    .padding(Theme.Spacing.md)
                                    .liquidGlass(cornerRadius: Theme.Radius.card)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    .padding(Theme.Spacing.md)
                }
            }
            .navigationTitle(lang.s("widgets.gallery.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(lang.s("common.done")) { dismiss() }
                }
            }
        }
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
    func performDrop(info: DropInfo) -> Bool { dragging = nil; store.persist(); return true }
}
