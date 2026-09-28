import SwiftUI

/// Open tasks you can check off in place; shows as many rows as the tile fits.
struct TasksWidget: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @State private var tasks: [TaskItem] = []
    @State private var loading = true
    @State private var busyId: String?

    private let rowHeight: CGFloat = 30
    private var open: [TaskItem] { tasks.filter { !$0.done } }

    var body: some View {
        GeometryReader { geo in
            let capacity = max(1, Int(geo.size.height / rowHeight))
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                if loading {
                    ProgressView().tint(Theme.Colors.accent)
                        .frame(maxWidth: .infinity, alignment: .center)
                } else if open.isEmpty {
                    Text(lang.s("tasks.empty"))
                        .font(Theme.Typography.subheadline)
                        .foregroundColor(Theme.Colors.secondaryText)
                } else {
                    ForEach(open.prefix(capacity)) { t in row(t) }
                    if open.count > capacity {
                        Text("+\(open.count - capacity)")
                            .font(Theme.Typography.caption)
                            .foregroundColor(Theme.Colors.tertiaryText)
                    }
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .task { await load() }
    }

    private func row(_ t: TaskItem) -> some View {
        Button {
            Task { await complete(t) }
        } label: {
            HStack(spacing: Theme.Spacing.sm) {
                Image(systemName: busyId == t.id ? "circle.dotted" : "circle")
                    .foregroundColor(Theme.Colors.accent)
                Text(t.text)
                    .font(Theme.Typography.subheadline)
                    .foregroundColor(Theme.Colors.primaryText)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
        }
        .buttonStyle(.plain)
        .disabled(busyId != nil)
    }

    private func load() async {
        loading = true
        let res = try? await state.api.getTasks()
        tasks = res?.items ?? []
        loading = false
    }

    private func complete(_ t: TaskItem) async {
        busyId = t.id
        defer { busyId = nil }
        try? await state.api.setTaskDone(id: t.id, done: true)
        await load()
    }
}
