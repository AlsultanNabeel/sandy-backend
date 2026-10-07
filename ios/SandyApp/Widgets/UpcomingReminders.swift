// KEEP IDENTICAL: copied in SandyApp/Widgets/ and SandyWidget/. The app writes it to the app
// group and the widget reads it, so both targets must compile the same definition.

import Foundation

/// The next reminders' rings, soonest first: the widget shows each until its time, then the
/// next, with no app running.
struct UpcomingReminders: Codable, Equatable {
    struct Ring: Codable, Equatable {
        let text: String
        let at: Date
    }

    var rings: [Ring]

    /// The app-group key it is kept under.
    static let key = "upcoming_reminders"
    /// How many the app writes: enough for a day's timeline, not a whole list.
    static let limit = 5

    /// What to show from `now` on: the ring shown from each date (nil: none left).
    func timeline(from now: Date) -> [(date: Date, ring: Ring?)] {
        let ahead = rings.filter { $0.at > now }.sorted { $0.at < $1.at }
        var out: [(date: Date, ring: Ring?)] = [(now, ahead.first)]
        for (i, ring) in ahead.enumerated() {
            out.append((ring.at, i + 1 < ahead.count ? ahead[i + 1] : nil))
        }
        return out
    }
}
