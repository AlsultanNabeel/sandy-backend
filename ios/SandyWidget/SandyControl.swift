// زر «تكلّم مع ساندي» بمركز التحكم (iOS 18): مكالمة صوتية عبر sandy://call.

import AppIntents
import SwiftUI
import WidgetKit

struct TalkToSandyControl: ControlWidget {
    static let kind = "com.sandy.app.control.talk"

    /// As the app last wrote it to the App Group (default Arabic).
    private var isArabic: Bool {
        UserDefaults(suiteName: SandyLinks.appGroup)?.string(forKey: "app_lang") != "en"
    }

    var body: some ControlWidgetConfiguration {
        let ar = isArabic
        return StaticControlConfiguration(kind: Self.kind) {
            ControlWidgetButton(action: TalkToSandyIntent()) {
                Label(ar ? "تكلّم مع ساندي" : "Talk to Sandy", systemImage: "waveform")
            }
        }
        .displayName(LocalizedStringResource(stringLiteral: ar ? "تكلّم مع ساندي" : "Talk to Sandy"))
        .description(LocalizedStringResource(stringLiteral: ar
            ? "يفتح مكالمة صوتية مع ساندي."
            : "Opens a live voice call with Sandy."))
    }
}
