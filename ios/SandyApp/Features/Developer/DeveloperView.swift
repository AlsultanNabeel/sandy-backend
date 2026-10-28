import SwiftUI

/// The developer screen: which server the app talks to, and the owner's trace and cost
/// pages. Shown when `DeveloperAccess` says so (Profile, and the staging badge).
struct DeveloperView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @State private var switching = false
    @State private var unsent = false

    var body: some View {
        ZStack {
            SandyBackground()
            ScrollView {
                VStack(spacing: Theme.Spacing.lg) {
                    serverCard
                    if state.stage == .chat {
                        SandyCard {
                            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                                row(icon: "list.bullet.rectangle", titleKey: "developer.traces") { TracesView() }
                                row(icon: "dollarsign.circle", titleKey: "developer.costs") { CostsView() }
                            }
                        }
                    }
                }
                .padding(Theme.Spacing.md)
            }
        }
        .navigationTitle(lang.s("developer.title"))
        .navigationBarTitleDisplayMode(.inline)
    }

    private var serverCard: some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                SectionHeader(title: lang.s("developer.server"))
                Picker(lang.s("developer.server"), selection: Binding(
                    get: { state.server },
                    set: { target in switchTo(target) })) {
                    ForEach(Backend.Server.allCases, id: \.self) { server in
                        Text(lang.s("developer.\(server.rawValue)")).tag(server)
                    }
                }
                .pickerStyle(.segmented)
                .disabled(switching)
                Text(lang.s(switching ? "developer.switching" : "developer.serverNote"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                if unsent {
                    SandyNotice(lang.s("developer.unsent"), kind: .gentleWarning)
                }
            }
        }
    }

    private func switchTo(_ target: Backend.Server) {
        guard target != state.server, !switching else { return }
        switching = true
        unsent = false
        Task {
            let outcome = await state.switchServer(to: target)
            unsent = outcome == .unsent
            switching = false
        }
    }

    private func row<Destination: View>(icon: String, titleKey: String,
                                        @ViewBuilder destination: @escaping () -> Destination) -> some View {
        NavigationLink(destination: destination) {
            HStack(spacing: Theme.Spacing.md) {
                Image(systemName: icon)
                    .scaledFont(Theme.Icon.md, weight: .semibold)
                    .foregroundColor(Theme.Colors.accent)
                    .frame(width: 28)
                Text(lang.s(titleKey))
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                Spacer(minLength: 0)
                Image(systemName: "chevron.forward")
                    .scaledFont(Theme.Icon.sm, weight: .semibold)
                    .foregroundColor(Theme.Colors.tertiaryText)
            }
            .padding(.vertical, Theme.Spacing.xs)
        }
        .buttonStyle(.plain)
    }
}

/// Shown over every screen while the app is on staging; tapping it opens the developer
/// screen, so the way back is there even signed out.
struct StagingBadge: View {
    @EnvironmentObject var lang: LanguageManager
    @State private var open = false

    var body: some View {
        Button { open = true } label: {
            Text(lang.s("developer.badge"))
                .font(Theme.Typography.caption.weight(.bold))
                .foregroundColor(.white)
                .padding(.horizontal, Theme.Spacing.sm)
                .padding(.vertical, 3)
                .background(Capsule().fill(Color.orange))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(lang.s("developer.staging"))
        .sheet(isPresented: $open) {
            NavigationStack { DeveloperView() }
        }
    }
}
