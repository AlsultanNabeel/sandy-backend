import SwiftUI

/// A short message on the main screen that outlives the screen that posted it: «reset my
/// data» rebuilds the main screen, and its «done» shows on the new one.
@MainActor
final class NoticeCenter: ObservableObject {
    static let shared = NoticeCenter()

    struct Notice: Identifiable, Equatable {
        let id = UUID()
        let text: String
    }

    @Published private(set) var notice: Notice?

    func post(_ text: String) {
        notice = Notice(text: text)
        Announce.say(text)
    }

    /// Its time ran out (a newer one may have replaced it).
    func expire(_ id: UUID) {
        if notice?.id == id { notice = nil }
    }

    /// Signed out: a message still up goes with the session.
    func drop() {
        notice = nil
    }
}

private struct NoticeBar: View {
    let notice: NoticeCenter.Notice

    var body: some View {
        HStack(spacing: Theme.Spacing.md) {
            Image(systemName: "checkmark.circle.fill").foregroundColor(Theme.Colors.success)
            Text(notice.text)
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.primaryText)
                .lineLimit(2)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.vertical, 12)
        .liquidGlass(cornerRadius: 18)
        .padding(.horizontal, Theme.Spacing.md)
        .transition(.move(edge: .top).combined(with: .opacity))
        .onTapGesture { withAnimation { NoticeCenter.shared.expire(notice.id) } }
        .task(id: notice.id) {
            try? await Task.sleep(for: .seconds(3))
            withAnimation { NoticeCenter.shared.expire(notice.id) }
        }
    }
}

private struct NoticeOverlay: ViewModifier {
    @ObservedObject private var center = NoticeCenter.shared

    func body(content: Content) -> some View {
        content
            .overlay(alignment: .top) {
                if let notice = center.notice { NoticeBar(notice: notice).padding(.top, 8) }
            }
            .animation(Animation.spring(response: 0.4, dampingFraction: 0.85).reduced, value: center.notice?.id)
    }
}

extension View {
    /// Shows the current short message at the top.
    func noticeOverlay() -> some View {
        modifier(NoticeOverlay())
    }
}
