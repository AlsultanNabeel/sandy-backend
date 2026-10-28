import SwiftUI

/// Every turn the server kept, newest first; a row opens the turn whole.
struct TracesView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store = OwnerStore()

    var body: some View {
        List {
            if !store.notice.isEmpty {
                SandyNotice(store.notice, kind: .gentleWarning).listRowBackground(Color.clear)
            } else if store.traces.isEmpty && !store.loading {
                Text(lang.s("developer.tracesEmpty")).foregroundColor(Theme.Colors.secondaryText)
            }
            ForEach(store.traces) { trace in
                NavigationLink { TraceDetailView(id: trace.id) } label: { TraceRow(trace: trace) }
            }
        }
        .overlay { if store.loading && store.traces.isEmpty { ProgressView() } }
        .navigationTitle(lang.s("developer.traces"))
        .navigationBarTitleDisplayMode(.inline)
        .task { await store.loadTraces(api: state.api) }
        .refreshable { await store.loadTraces(api: state.api) }
    }
}

private struct TraceRow: View {
    @EnvironmentObject var lang: LanguageManager
    let trace: Trace

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(lang.s("developer.\(trace.source)"))
                    .font(Theme.Typography.headline)
                if trace.error != nil {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundColor(.orange)
                }
                Spacer()
                Text(TraceFormat.usd(trace.costUsd)).font(Theme.Typography.caption)
            }
            Text(trace.tools.map(\.name).joined(separator: " · "))
                .font(Theme.Typography.caption)
                .foregroundColor(Theme.Colors.secondaryText)
            HStack {
                Text(TraceFormat.when(trace))
                Spacer()
                Text(TraceFormat.ms(trace.msTotal))
            }
            .font(Theme.Typography.caption)
            .foregroundColor(Theme.Colors.tertiaryText)
        }
    }
}

/// One turn: its words when it is the owner's own, every tool with what it was given and
/// what it answered, every model call with its tokens.
struct TraceDetailView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @StateObject private var store = OwnerStore()
    let id: String

    var body: some View {
        List {
            if !store.notice.isEmpty {
                SandyNotice(store.notice, kind: .gentleWarning).listRowBackground(Color.clear)
            }
            if let t = store.opened {
                Section {
                    LabeledContent(lang.s("developer.\(t.source)"), value: t.routedBy)
                    LabeledContent(TraceFormat.when(t), value: TraceFormat.ms(t.msTotal))
                    LabeledContent(lang.s("developer.total"), value: TraceFormat.usd(t.costUsd))
                    Text(TraceFormat.tokens(t.tokensIn, t.tokensOut, lang))
                    if let error = t.error { LabeledContent(lang.s("developer.error"), value: error) }
                }
                Section {
                    if t.request == nil && t.reply == nil {
                        Text(lang.s("developer.noWords")).foregroundColor(Theme.Colors.secondaryText)
                    }
                    if let request = t.request { words("developer.request", request) }
                    if let reply = t.reply { words("developer.reply", reply) }
                }
                if !t.tools.isEmpty {
                    Section(lang.s("developer.tools")) {
                        ForEach(Array(t.tools.enumerated()), id: \.offset) { _, tool in
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Image(systemName: tool.ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                                        .foregroundColor(tool.ok ? .green : .orange)
                                    Text(tool.name).font(Theme.Typography.headline)
                                    Spacer()
                                    Text(TraceFormat.ms(tool.ms)).font(Theme.Typography.caption)
                                }
                                if let args = tool.args { code("developer.args", args) }
                                if let result = tool.result { code("developer.result", result) }
                            }
                        }
                    }
                }
                if !t.modelCalls.isEmpty {
                    Section(lang.s("developer.modelCalls")) {
                        ForEach(Array(t.modelCalls.enumerated()), id: \.offset) { _, call in
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(call.provider) · \(call.model)").font(Theme.Typography.headline)
                                Text(TraceFormat.tokens(call.tokensIn, call.tokensOut, lang))
                                    .font(Theme.Typography.caption)
                            }
                        }
                    }
                }
            }
        }
        .overlay { if store.loading && store.opened == nil { ProgressView() } }
        .navigationBarTitleDisplayMode(.inline)
        .task { await store.open(id, api: state.api) }
    }

    private func words(_ key: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(lang.s(key)).font(Theme.Typography.caption).foregroundColor(Theme.Colors.secondaryText)
            Text(text).textSelection(.enabled)
        }
    }

    private func code(_ key: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(lang.s(key)).font(Theme.Typography.caption).foregroundColor(Theme.Colors.secondaryText)
            Text(text).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                .environment(\.layoutDirection, .leftToRight)
        }
    }
}

/// How the developer pages write money, time and tokens.
@MainActor
enum TraceFormat {
    static func usd(_ value: Double) -> String {
        "$" + value.formatted(.number.precision(.fractionLength(2...5)).locale(Locale(identifier: "en_US")))
    }

    static func ms(_ value: Int) -> String {
        value >= 1000 ? String(format: "%.1fs", Double(value) / 1000) : "\(value)ms"
    }

    static func when(_ trace: Trace) -> String {
        guard let date = trace.date else { return trace.at }
        return date.formatted(Date.FormatStyle(date: .abbreviated, time: .shortened).locale(AppLocale.current))
    }

    static func tokens(_ tokensIn: Int, _ tokensOut: Int, _ lang: LanguageManager) -> String {
        String(format: lang.s("developer.tokens"),
               tokensIn.formatted(.number.locale(AppLocale.current)),
               tokensOut.formatted(.number.locale(AppLocale.current)))
    }
}
