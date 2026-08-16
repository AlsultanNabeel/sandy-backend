import SwiftUI

/// شاشة "محتوى يهمّك" — ساندي بتجمع محتوى من اهتماماتك اللي رصدتها من حديثك معها
/// (عبر `/api/share/suggest`)، وبتخليك تحفظ أي بطاقة تعجبك أو تشيلها. مبدّل علوي
/// بين المقترح والمحفوظ. نمط الستور المعتمد: الجلب بمهمة يملكها الستور، فإلغاء
/// إيماءة الواجهة ما بيلغيه.
struct ShareContentView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager

    @StateObject private var store = ShareContentStore()
    @State private var segment: Segment = .suggested

    /// المقطع المعروض — مقترح إلك / المحفوظ.
    enum Segment: Hashable { case suggested, saved }

    var body: some View {
        ZStack {
            SandyBackground()

            VStack(spacing: 0) {
                segmentPicker

                if !store.notice.isEmpty {
                    SandyNotice(store.notice, kind: .gentleWarning)
                        .padding(.horizontal, Theme.Spacing.md)
                        .padding(.top, Theme.Spacing.sm)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                content
            }
        }
        .navigationTitle(lang.s("tabs.shareContent"))
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                if segment == .suggested {
                    SandyButton(title: lang.s("shareContent.refresh"),
                                systemImage: "arrow.clockwise",
                                style: .secondary) {
                        Task { await store.loadSuggested(api: state.api) }
                    }
                }
            }
        }
        .animation(.easeInOut(duration: 0.25), value: store.notice)
        .animation(.spring(response: 0.45, dampingFraction: 0.85), value: store.saved.map(\.id))
        .task {
            await store.loadSuggested(api: state.api)
            await store.loadSaved(api: state.api)
        }
        .refreshable {
            if segment == .suggested { await store.loadSuggested(api: state.api) }
            else { await store.loadSaved(api: state.api) }
        }
    }

    private var segmentPicker: some View {
        Picker("", selection: $segment) {
            Text(lang.s("shareContent.seg.suggested")).tag(Segment.suggested)
            Text(lang.s("shareContent.seg.saved")).tag(Segment.saved)
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, Theme.Spacing.sm)
    }

    @ViewBuilder
    private var content: some View {
        ScrollView {
            VStack(spacing: Theme.Spacing.md) {
                switch segment {
                case .suggested: suggestedBody
                case .saved:     savedBody
                }
            }
            .padding(Theme.Spacing.md)
            .padding(.bottom, Theme.Spacing.xxl + Theme.Spacing.xl)
        }
    }

    // MARK: - مقترح إلك

    @ViewBuilder
    private var suggestedBody: some View {
        if store.loadingSuggested {
            ProgressView().tint(Theme.Colors.accent).padding(.top, Theme.Spacing.xxl)
        } else if store.topic.isEmpty {
            emptyState(icon: "sparkles",
                       text: lang.s("shareContent.empty.hint"))
        } else if store.suggested.isEmpty {
            emptyState(icon: "tray",
                       text: lang.s("shareContent.empty.results"))
        } else {
            header
            ForEach(store.suggested) { item in
                contentCard(item, saved: false)
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            Text(lang.s("shareContent.intro"))
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
            Text("\(lang.s("shareContent.topic")) « \(store.topic) »")
                .font(Theme.Typography.headline)
                .foregroundColor(Theme.Colors.accent)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - المحفوظ

    @ViewBuilder
    private var savedBody: some View {
        if store.loadingSaved {
            ProgressView().tint(Theme.Colors.accent).padding(.top, Theme.Spacing.xxl)
        } else if store.saved.isEmpty {
            emptyState(icon: "bookmark", text: lang.s("shareContent.empty.saved"))
        } else {
            ForEach(store.saved) { item in
                contentCard(item, saved: true)
            }
        }
    }

    // MARK: - بطاقة محتوى

    private func contentCard(_ item: SharedContentItem, saved: Bool) -> some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                Text(item.displayTitle)
                    .font(Theme.Typography.headline)
                    .foregroundColor(Theme.Colors.primaryText)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if !item.text.isEmpty {
                    Text(item.text)
                        .font(Theme.Typography.caption)
                        .foregroundColor(Theme.Colors.secondaryText)
                        .lineLimit(3)
                }

                HStack(spacing: Theme.Spacing.md) {
                    if let url = item.link {
                        Link(destination: url) {
                            Label(prettyHost(item.url), systemImage: "link")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.accent)
                                .lineLimit(1)
                        }
                    }

                    Spacer(minLength: 0)

                    if saved {
                        Button {
                            store.remove(api: state.api, item: item)
                        } label: {
                            Label(lang.s("shareContent.remove"), systemImage: "trash")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.danger)
                        }
                        .buttonStyle(.plain)
                    } else {
                        Button {
                            Task { await store.save(api: state.api, item: item) }
                        } label: {
                            Label(lang.s(store.isSaved(item) ? "shareContent.saved"
                                                             : "shareContent.save"),
                                  systemImage: store.isSaved(item) ? "checkmark.circle.fill"
                                                                   : "bookmark")
                                .font(Theme.Typography.caption)
                                .foregroundColor(Theme.Colors.accent)
                        }
                        .buttonStyle(.plain)
                        .disabled(store.isSaved(item))
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func emptyState(icon: String, text: String) -> some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: icon)
                .font(.system(size: Theme.Icon.xl))
                .foregroundColor(Theme.Colors.accent.opacity(0.5))
            Text(text)
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.secondaryText)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, Theme.Spacing.xxl)
        .padding(.horizontal, Theme.Spacing.lg)
    }

    /// اسم النطاق فقط للعرض (بدون البروتوكول والمسار الطويل).
    private func prettyHost(_ s: String) -> String {
        URL(string: s)?.host?.replacingOccurrences(of: "www.", with: "") ?? s
    }
}

// MARK: - الستور (مصدر الحقيقة للمحتوى المقترح والمحفوظ)

// MARK: - النموذج

/// بطاقة محتوى مقترح أو محفوظ. المقترح بلا `serverId` (لسا ما اتحفظ)؛ المحفوظ
/// بيحمل `id` من الباك-إند للحذف. `id` للعرض ثابت داخل الجلسة.
struct SharedContentItem: Identifiable {
    let id: String
    let title: String
    let url: String
    let text: String

    /// عنوان العرض — لو فاضي نرجع للرابط.
    var displayTitle: String { title.isEmpty ? url : title }
    var link: URL? { url.isEmpty ? nil : URL(string: url) }
}

// MARK: - نداءات الباك-إند
