import Foundation

/// Who sees the developer screen: an account the server turned `dev_tools` on for
/// (`SANDY_FLAGS`), and anyone on staging, so the way back to production is never hidden.
enum DeveloperAccess {
    static let flag = "dev_tools"

    static func shows(on: Set<String>, server: Backend.Server) -> Bool {
        on.contains(flag) || server == .staging
    }
}
