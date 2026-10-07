import SwiftUI

/// «ليش قطعة مش ظاهرة؟» — the server's check (`GET /api/diagnose`) in plain words: each
/// board (connected or not, its version, when it was last heard), parts a board has that
/// the app does not know yet, parts the app knows that no board has announced, and
/// whether the screen and the camera were set up.
struct DiagnoseView: View {
    @EnvironmentObject var state: AppState
    @EnvironmentObject var lang: LanguageManager
    @State private var report: DiagnoseReport?
    @State private var failed = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                if let report {
                    boards(report)
                    checks(report)
                    if let logins = report.brokerLoginsToRevoke, !logins.isEmpty {
                        toRevoke(logins)
                    }
                } else if failed {
                    SandyNotice(lang.s("robot.diag.failed"), kind: .gentleWarning)
                } else {
                    SkeletonList(rows: 3)
                }
            }
            .padding(Theme.Spacing.md)
        }
        .background(SandyBackground())
        .navigationTitle(lang.s("robot.hub.diagnose"))
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        do {
            report = try await state.api.diagnose()
            failed = false
        } catch {
            failed = report == nil
        }
    }

    private func boards(_ r: DiagnoseReport) -> some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                SectionHeader(title: lang.s("robot.diag.boards"))
                if r.nodes.isEmpty {
                    line("exclamationmark.triangle.fill", lang.s("robot.diag.noBoards"), Theme.Colors.warn)
                }
                ForEach(r.nodes, id: \.nodeId) { n in
                    line(n.online == true ? "checkmark.circle.fill" : "xmark.circle.fill",
                         String(format: lang.s(n.online == true ? "robot.diag.online" : "robot.diag.offline"),
                                n.nodeId, n.firmware ?? "?", BlockDate.text(n.lastSeen) ?? "—"),
                         n.online == true ? Theme.Colors.success : Theme.Colors.warn)
                }
            }
        }
    }

    private func checks(_ r: DiagnoseReport) -> some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                SectionHeader(title: lang.s("robot.diag.parts"))
                let c = r.checks
                if c.declaredButNoCatalogueEntry.isEmpty && c.catalogueHasButBoardNeverDeclared.isEmpty {
                    line("checkmark.circle.fill", lang.s("robot.diag.allKnown"), Theme.Colors.success)
                }
                if !c.declaredButNoCatalogueEntry.isEmpty {
                    line("questionmark.circle.fill",
                         String(format: lang.s("robot.diag.unknownParts"),
                                c.declaredButNoCatalogueEntry.joined(separator: lang.s("common.listSeparator"))),
                         Theme.Colors.warn)
                }
                if !c.catalogueHasButBoardNeverDeclared.isEmpty {
                    line("minus.circle.fill",
                         String(format: lang.s("robot.diag.missingParts"),
                                c.catalogueHasButBoardNeverDeclared.joined(separator: lang.s("common.listSeparator"))),
                         Theme.Colors.secondaryText)
                }
                line(c.screenDeviceExists ? "checkmark.circle.fill" : "xmark.circle.fill",
                     lang.s(c.screenDeviceExists ? "robot.diag.screenOk" : "robot.diag.screenMissing"),
                     c.screenDeviceExists ? Theme.Colors.success : Theme.Colors.warn)
                line(c.cameraDevicesExist.isEmpty ? "xmark.circle.fill" : "checkmark.circle.fill",
                     lang.s(c.cameraDevicesExist.isEmpty ? "robot.diag.cameraMissing" : "robot.diag.cameraOk"),
                     c.cameraDevicesExist.isEmpty ? Theme.Colors.secondaryText : Theme.Colors.success)
            }
        }
    }

    /// The project owner's account only (the server sends it to no one else): released
    /// boards whose own broker login is still live, to revoke on the broker by hand.
    private func toRevoke(_ logins: [DiagnoseReport.Revoke]) -> some View {
        SandyCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                SectionHeader(title: lang.s("robot.diag.revokeTitle"))
                Text(lang.s("robot.diag.revokeHow"))
                    .font(Theme.Typography.caption)
                    .foregroundColor(Theme.Colors.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(logins, id: \.device) { l in
                    line("key.slash", "\(l.user) — \(l.device)", Theme.Colors.warn)
                }
            }
        }
    }

    private func line(_ icon: String, _ text: String, _ color: Color) -> some View {
        HStack(alignment: .top, spacing: Theme.Spacing.sm) {
            Image(systemName: icon).foregroundColor(color).accessibilityHidden(true)
            Text(text)
                .font(Theme.Typography.subheadline)
                .foregroundColor(Theme.Colors.primaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
    }
}

/// What `GET /api/diagnose` answers (the parts this screen reads).
struct DiagnoseReport: Decodable {
    struct Node: Decodable {
        let nodeId: String
        let online: Bool?
        let firmware: String?
        let lastSeen: String?

        enum CodingKeys: String, CodingKey {
            case online, firmware
            case nodeId = "node_id"
            case lastSeen = "last_seen"
        }
    }

    struct Checks: Decodable {
        let declaredButNoCatalogueEntry: [String]
        let catalogueHasButBoardNeverDeclared: [String]
        let screenDeviceExists: Bool
        let cameraDevicesExist: [String]

        enum CodingKeys: String, CodingKey {
            case declaredButNoCatalogueEntry = "declared_but_no_catalogue_entry"
            case catalogueHasButBoardNeverDeclared = "catalogue_has_but_board_never_declared"
            case screenDeviceExists = "screen_device_exists"
            case cameraDevicesExist = "camera_devices_exist"
        }
    }

    struct Revoke: Decodable {
        let device: String
        let user: String
    }

    let nodes: [Node]
    let checks: Checks
    /// Only on the project owner's account.
    let brokerLoginsToRevoke: [Revoke]?

    enum CodingKeys: String, CodingKey {
        case nodes, checks
        case brokerLoginsToRevoke = "broker_logins_to_revoke"
    }
}

extension APIClient {
    func diagnose() async throws -> DiagnoseReport {
        try await fetch("/api/diagnose")
    }
}
