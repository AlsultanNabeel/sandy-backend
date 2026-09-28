import CoreSpotlight
import Foundation
import UniformTypeIdentifiers

/// يفهرس محتوى ساندي بـ Spotlight؛ المعرّف `sandy:<type>:<id>`، ونطاق لكل نوع.
/// `replace` بيمسح نطاق النوع ويعيد فهرسته، والنداءات متسلسلة فما بيتداخل مسح مع فهرسة.
@MainActor
enum SpotlightIndexer {
    enum Kind: String, CaseIterable {
        case task, reminder, journal, book, memory
        var domain: String { "sandy.\(rawValue)" }
    }

    struct Entry {
        let id: String
        let title: String
        let detail: String
    }

    private static var chain: Task<Void, Never>?

    static func identifier(_ kind: Kind, _ id: String) -> String { "sandy:\(kind.rawValue):\(id)" }

    static func replace(_ kind: Kind, with entries: [Entry]) {
        let previous = chain
        let rows = entries.filter { !$0.id.isEmpty && !$0.title.isEmpty }
        chain = Task { @MainActor in
            await previous?.value
            let index = CSSearchableIndex.default()
            try? await index.deleteSearchableItems(withDomainIdentifiers: [kind.domain])
            guard !rows.isEmpty else { return }
            let items = rows.map { e -> CSSearchableItem in
                let attrs = CSSearchableItemAttributeSet(contentType: UTType.text)
                attrs.title = e.title
                attrs.contentDescription = e.detail
                return CSSearchableItem(uniqueIdentifier: SpotlightIndexer.identifier(kind, e.id),
                                        domainIdentifier: kind.domain,
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

    static func indexTasks(_ items: [TaskItem]) {
        replace(.task, with: items.filter { !$0.done }.map {
            Entry(id: $0.id, title: $0.text, detail: $0.note)
        })
    }

    static func indexReminders(_ items: [ReminderItem]) {
        replace(.reminder, with: items.map {
            Entry(id: $0.id, title: $0.text, detail: $0.note)
        })
    }

    static func indexJournal(_ items: [JournalEntry]) {
        replace(.journal, with: items.map {
            Entry(id: $0.id, title: headline($0.text), detail: $0.text)
        })
    }

    static func indexBooks(_ items: [BookItem]) {
        replace(.book, with: items.map {
            Entry(id: $0.id, title: $0.title, detail: $0.author)
        })
    }

    static func indexMemory(_ items: [MemoryFact]) {
        replace(.memory, with: items.map {
            Entry(id: $0.id, title: headline($0.text), detail: $0.text)
        })
    }
}
