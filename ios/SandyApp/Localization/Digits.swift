import Foundation

/// One reading of a number the user typed, for every field that takes one (budget, amounts,
/// focus minutes, a dimmer level, a pairing code). Arabic-Indic and Persian digits are digits;
/// the plain comma and the Arabic thousands mark (٬) group thousands and are dropped; the point
/// and the Arabic decimal mark (٫) start the fraction.
enum Digits {
    /// The text with every digit made Latin; nothing else changes.
    static func latin(_ text: String) -> String {
        String(text.map { ch -> Character in
            if !ch.isASCII, ch.isNumber, let d = ch.wholeNumberValue { return Character(String(d)) }
            return ch
        })
    }

    /// A typed decimal number, or nil when it is not one.
    static func number(_ text: String) -> Double? {
        var clean = ""
        for ch in latin(text.trimmingCharacters(in: .whitespacesAndNewlines)) {
            switch ch {
            case ",", "٬": continue
            case "٫": clean.append(".")
            default: clean.append(ch)
            }
        }
        return clean.isEmpty ? nil : Double(clean)
    }

    /// A typed whole number, or nil (a fraction is not one).
    static func integer(_ text: String) -> Int? {
        guard let value = number(text), value == value.rounded(), abs(value) < Double(Int.max)
        else { return nil }
        return Int(value)
    }
}
