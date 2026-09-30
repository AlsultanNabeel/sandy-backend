import CoreSpotlight
import Foundation
import UniformTypeIdentifiers

/// يفهرس محتوى ساندي بـ Spotlight؛ المعرّف `sandy:<type>:<id>`، ونطاق لكل نوع.
/// `replace` بيمسح نطاق النوع ويعيد فهرسته، والنداءات متسلسلة فما بيتداخل مسح مع فهرسة.
@MainActor
enum SpotlightIndexer {
    /// item = a list row, entry = a log row; the domain adds the list so each list
    /// replaces only its own rows.
    enum Kind: String, CaseIterable {
        case item, reminder, entry, memory
    }

    struct Entry {
        let id: String
        let title: String
        let detail: String
    }

    private static var chain: Task<Void, Never>?

    static func identifier(_ kind: Kind, _ id: String) -> String { "sandy:\(kind.rawValue):\(id)" }

    static func replace(_ kind: Kind, scope: String = "", with entries: [Entry]) {
        let domain = scope.isEmpty ? "sandy.\(kind.rawValue)" : "sandy.\(kind.rawValue).\(scope)"
        let previous = chain
        let rows = entries.filter { !$0.id.isEmpty && !$0.title.isEmpty }
        chain = Task { @MainActor in
            await previous?.value
            let index = CSSearchableIndex.default()
            try? await index.deleteSearchableItems(withDomainIdentifiers: [domain])
            guard !rows.isEmpty else { return }
            let items = rows.map { e -> CSSearchableItem in
                let attrs = CSSearchableItemAttributeSet(contentType: UTType.text)
                attrs.title = e.title
                attrs.contentDescription = e.detail
                return CSSearchableItem(uniqueIdentifier: SpotlightIndexer.identifier(kind, e.id),
                                        domainIdentifier: domain,
                                        attributeSet: attrs)
            }
            try? await index.indexSearchableItems(items)
        }
    }

    static func deleteAll() {
        let previous = chain
        chain = Task { @MainActor in
            await previous?.value
            try? await CSSearchableIndex.default().deleteAllSearchableItems()
        }
    }


    /// أول سطر، أقصى ٨٠ حرف.
    private static func headline(_ text: String) -> String {
        let first = text.split(whereSeparator: \.isNewline).first.map(String.init) ?? text
        let trimmed = first.trimmingCharacters(in: .whitespaces)
        return trimmed.count > 80 ? String(trimmed.prefix(80)) + "…" : trimmed
    }

    /// Open rows of one list; the list rides in the id so a tap opens the right screen.
    static func indexItems(list: String, _ items: [ListItem]) {
        replace(.item, scope: list, with: items.filter { !$0.done }.map {
            Entry(id: list + ":" + $0.id, title: $0.text, detail: "")
        })
    }

    static func indexReminders(_ items: [ScheduleItem]) {
        replace(.reminder, with: items.map { Entry(id: $0.id, title: $0.text, detail: "") })
    }

    static func indexEntries(_ items: [LogEntry]) {
        replace(.entry, with: items.map {
            Entry(id: $0.id, title: headline($0.text), detail: $0.text)
        })
    }

    static func indexMemory(_ items: [MemoryFact]) {
        replace(.memory, with: items.map {
            Entry(id: $0.id, title: headline($0.text), detail: $0.text)
        })
    }
}
