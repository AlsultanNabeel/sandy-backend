import SwiftUI

/// What was spent in the last thirty days: the total, by user, by source.
struct CostsView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store = OwnerStore()

    var body: some View {
        List {
            if !store.notice.isEmpty {
                SandyNotice(store.notice, kind: .gentleWarning).listRowBackground(Color.clear)
            }
            if let c = store.costs {
                Section {
                    LabeledContent(lang.s("developer.total"), value: TraceFormat.usd(c.totalUsd))
                        .font(Theme.Typography.headline)
                    Text(String(format: lang.s("developer.lastDays"),
                                c.days.formatted(.number.locale(AppLocale.current))))
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                }
                Section(lang.s("developer.byUser")) {
                    ForEach(c.byUser, id: \.self) { user in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack {
                                Text(user.label.isEmpty ? user.userId : user.label)
                                    .font(Theme.Typography.headline).lineLimit(1)
                                Spacer()
                                Text(TraceFormat.usd(user.usd))
                            }
                            Text(turns(user.turns) + " · " + TraceFormat.tokens(user.tokensIn, user.tokensOut, lang))
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.secondaryText)
                        }
                    }
                }
                Section(lang.s("developer.bySource")) {
                    ForEach(c.bySource, id: \.self) { source in
                        LabeledContent(lang.s("developer.\(source.source)"),
                                       value: turns(source.turns) + " · " + TraceFormat.usd(source.usd))
                    }
                }
            }
        }
        .overlay { if store.loading && store.costs == nil { ProgressView() } }
        .navigationTitle(lang.s("developer.costs"))
        .navigationBarTitleDisplayMode(.inline)
        .task { await store.loadCosts(api: state.api) }
        .refreshable { await store.loadCosts(api: state.api) }
    }

    private func turns(_ n: Int) -> String {
        String(format: lang.s("developer.turns"), n.formatted(.number.locale(AppLocale.current)))
    }
}
