import Foundation
import SwiftUI
import UniformTypeIdentifiers

// ─────────────────────────────────────────────────────────────────────────
//  WidgetDashboard — a per-tab, iPhone-widget-style customizable grid.
//
//  Each feature is a tile. Long-press enters edit mode (tiles jiggle); then:
//    • drag a tile to reorder,
//    • tap the − badge to hide it,
//    • tap the ⤢ badge to resize (small ↔ large).
//  Layout (order + size + hidden) persists per tab on the device. On top of
//  that the OWNER can force-hide any feature centrally (server layer): those
//  never appear and can't be re-shown from settings.
//
//  Two sizes only (small = half width, large = full width), matching the ask.
//  All the feature code stays; this only decides presentation.
// ─────────────────────────────────────────────────────────────────────────

enum WidgetSize: String, Codable { case small, large }

/// Persisted per-tile state (order is the array order).
struct DashboardItem: Identifiable, Codable, Equatable {
    let key: String
    var size: WidgetSize = .small
    var hidden: Bool = false          // hidden BY THE USER
    var id: String { key }
}

/// Static catalog entry — how a feature looks + where it goes. Not persisted.
struct WidgetSpec: Identifiable {
    let key: String
    let icon: String
    let titleKey: String
    let tint: Color
    let destination: () -> AnyView
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

    /// Owner-hidden set from the server; forces those out everywhere.
    func applyServerHidden(_ hidden: Set<String>) {
        serverHidden = hidden
    }

    /// What the tab shows normally: user order, minus owner-hidden and user-hidden.
    var shown: [DashboardItem] {
        items.filter { !serverHidden.contains($0.key) && !$0.hidden }
    }

    /// What edit mode shows: everything the owner allows (incl. user-hidden,
    /// rendered dimmed so the user can bring them back).
    var editable: [DashboardItem] {
        items.filter { !serverHidden.contains($0.key) }
    }

    // ── mutations (all persist) ─────────────────────────────────────────
    func toggleHidden(_ key: String) {
        guard let i = items.firstIndex(where: { $0.key == key }) else { return }
        items[i].hidden.toggle()
        persist()
    }

    func cycleSize(_ key: String) {
        guard let i = items.firstIndex(where: { $0.key == key }) else { return }
        items[i].size = items[i].size == .small ? .large : .small
        persist()
    }

    /// Move the dragged key to sit before `target` (live reflow while dragging).
    func relocate(_ dragged: String, before target: String) {
        guard dragged != target,
              let from = items.firstIndex(where: { $0.key == dragged }),
              let to = items.firstIndex(where: { $0.key == target }) else { return }
        let item = items.remove(at: from)
        let insertAt = items.firstIndex(where: { $0.key == target }) ?? to
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
        // Keep saved order/size/hidden for keys we still know; append new catalog
        // features (default small, shown); drop keys no longer in the catalog.
        var merged = saved.filter { spec($0.key) != nil }
        let present = Set(merged.map(\.key))
        for s in catalog where !present.contains(s.key) {
            merged.append(DashboardItem(key: s.key))
        }
        items = merged
    }
}

// MARK: - The grid

struct WidgetDashboard: View {
    @EnvironmentObject var lang: LanguageManager
    @ObservedObject var store: DashboardStore
    @State private var dragging: String?

    var body: some View {
        ScrollView {
            // Manual packing gives us spanning: small = half width, large = full.
            let rows = packed(store.editing ? store.editable : store.shown)
            VStack(spacing: Theme.Spacing.md) {
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    HStack(spacing: Theme.Spacing.md) {
                        ForEach(row) { item in tile(item) }
                        // A lone small tile keeps half width instead of stretching.
                        if rowSlots(row) == 1 { Color.clear.frame(maxWidth: .infinity) }
                    }
                }
            }
            .padding(Theme.Spacing.md)
            .animation(.spring(response: 0.35, dampingFraction: 0.8), value: store.items)
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(store.editing ? lang.s("common.done") : lang.s("widgets.edit")) {
                    withAnimation { store.editing.toggle() }
                    if !store.editing { store.persist() }
                }
            }
        }
    }

    /// Two columns; large tiles take both. Greedily pack items into rows.
    private func packed(_ list: [DashboardItem]) -> [[DashboardItem]] {
        var rows: [[DashboardItem]] = []
        var cur: [DashboardItem] = []
        var used = 0
        for it in list {
            let w = it.size == .large ? 2 : 1
            if used + w > 2 { rows.append(cur); cur = []; used = 0 }
            cur.append(it)
            used += w
            if used >= 2 { rows.append(cur); cur = []; used = 0 }
        }
        if !cur.isEmpty { rows.append(cur) }
        return rows
    }

    private func rowSlots(_ row: [DashboardItem]) -> Int {
        row.reduce(0) { $0 + ($1.size == .large ? 2 : 1) }
    }

    @ViewBuilder
    private func tile(_ item: DashboardItem) -> some View {
        let spec = store.spec(item.key)
        Group {
            if store.editing {
                editTile(item, spec: spec)
            } else if let spec {
                NavigationLink { spec.destination() } label: {
                    WidgetCard(spec: spec, size: item.size, lang: lang)
                }
                .buttonStyle(.plain)
            }
        }
    }

    // Edit mode: jiggle + − (hide) + ⤢ (resize), draggable to reorder.
    @ViewBuilder
    private func editTile(_ item: DashboardItem, spec: WidgetSpec?) -> some View {
        if let spec {
            WidgetCard(spec: spec, size: item.size, lang: lang)
                .opacity(item.hidden ? 0.35 : 1)
                .overlay(alignment: .topTrailing) { resizeBadge(item) }
                .overlay(alignment: .topLeading) { hideBadge(item) }
                .rotationEffect(.degrees(store.editing ? 0.6 : 0))
                .animation(.easeInOut(duration: 0.14).repeatForever(autoreverses: true),
                           value: store.editing)
                .onDrag {
                    dragging = item.key
                    return NSItemProvider(object: item.key as NSString)
                }
                .onDrop(of: [UTType.text],
                        delegate: WidgetDropDelegate(target: item.key, store: store,
                                                     dragging: $dragging))
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

    private func resizeBadge(_ item: DashboardItem) -> some View {
        Button { store.cycleSize(item.key) } label: {
            Image(systemName: item.size == .small
                  ? "arrow.up.left.and.arrow.down.right.circle.fill"
                  : "arrow.down.right.and.arrow.up.left.circle.fill")
                .font(.system(size: 22))
                .foregroundColor(Theme.Colors.accent)
                .background(Circle().fill(Theme.Colors.card))
        }
        .buttonStyle(.plain)
        .offset(x: 6, y: -6)
    }
}

/// One tile's face — icon + title, sized. Large also shows a subtitle.
private struct WidgetCard: View {
    let spec: WidgetSpec
    let size: WidgetSize
    let lang: LanguageManager

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Image(systemName: spec.icon)
                .font(.system(size: size == .large ? 26 : 20, weight: .semibold))
                .foregroundColor(spec.tint)
            Spacer(minLength: 0)
            Text(lang.s(spec.titleKey))
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.primaryText)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .frame(height: size == .large ? 120 : 96)
        .padding(Theme.Spacing.md)
        .liquidGlass(cornerRadius: Theme.Radius.card)
    }
}

/// Live reflow while dragging: as the finger passes a tile, the dragged one
/// slides in before it.
private struct WidgetDropDelegate: DropDelegate {
    let target: String
    let store: DashboardStore
    @Binding var dragging: String?

    func dropEntered(info: DropInfo) {
        guard let dragging, dragging != target else { return }
        withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
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
