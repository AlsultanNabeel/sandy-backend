import Foundation

// Namespace: chat — the conversation screen. STARTER stub — the ChatView
// migration agent fills the rest into this table (ar + en).
//
// Usage:  Text(lang.s("chat.title"))
enum L10nChat {
    static let ns = "chat"

    static let table = L10nTable(
        ar: [
            "title":        .text("ساندي"),
            "placeholder":  .text("اكتب لساندي…"),
            "typing":       .text("ساندي تكتب…"),
            "typingA11y":   .text("ساندي تكتب"),
            "send":         .text("إرسال"),
            "sendError":    .text("معلش، تعثّرت شوي وأنا أرد عليك — جرّب كمان مرة بعد لحظة 🌷"),
            "micStart":     .text("احكيني"),
            "micListening": .text("أسمعك… احكي"),
            "voiceDenied":  .text("محتاجة إذن المايك عشان أسمعك — فعّله من إعدادات الجوال 🌷"),
            "speakerOn":    .text("صوت ساندي شغّال"),
            "speakerOff":   .text("صوت ساندي مكتوم"),
            "liveCall":     .text("مكالمة صوتية"),
            "liveConnecting": .text("لحظة… بجهّز"),
            "liveListening":  .text("أسمعك…"),
            "liveThinking":   .text("بفكّر…"),
            "liveSpeaking":   .text("بحكي…"),
            "liveHint":     .text("احكي عادي، وأنا أرد — لمّا تسكت برد عليك"),
            "liveEnd":      .text("إنهاء المكالمة"),
            "history":      .text("سجل المحادثات"),
            "new":          .text("محادثة جديدة"),
            "searchPlaceholder": .text("دوّر بمحادثاتك…"),
            "historyEmpty": .text("ما في محادثات محفوظة بعد."),
            "untitled":     .text("محادثة"),
            "rename":       .text("إعادة تسمية"),
            "delete":       .text("حذف"),
            "renameTitle":  .text("اسم المحادثة"),
            "renamePlaceholder": .text("اكتب اسم جديد…"),
            "today":        .text("اليوم"),
            "yesterday":    .text("أمس"),
            "week":         .text("آخر سبعة أيام"),
            "older":        .text("أقدم"),
        ],
        en: [
            "title":        .text("Sandy"),
            "placeholder":  .text("Message Sandy…"),
            "typing":       .text("Sandy is typing…"),
            "typingA11y":   .text("Sandy is typing"),
            "send":         .text("Send"),
            "sendError":    .text("Sorry, I stumbled a little while replying — give it another try in a moment 🌷"),
            "micStart":     .text("Talk to me"),
            "micListening": .text("I'm listening… go ahead"),
            "voiceDenied":  .text("I need mic access to hear you — enable it in Settings 🌷"),
            "speakerOn":    .text("Sandy's voice is on"),
            "speakerOff":   .text("Sandy's voice is muted"),
            "liveCall":     .text("Voice call"),
            "liveConnecting": .text("One sec… getting ready"),
            "liveListening":  .text("Listening…"),
            "liveThinking":   .text("Thinking…"),
            "liveSpeaking":   .text("Speaking…"),
            "liveHint":     .text("Just talk — when you pause, I'll reply"),
            "liveEnd":      .text("End call"),
            "history":      .text("Chat history"),
            "new":          .text("New chat"),
            "searchPlaceholder": .text("Search your chats…"),
            "historyEmpty": .text("No saved chats yet."),
            "untitled":     .text("Chat"),
            "rename":       .text("Rename"),
            "delete":       .text("Delete"),
            "renameTitle":  .text("Chat name"),
            "renamePlaceholder": .text("Type a new name…"),
            "today":        .text("Today"),
            "yesterday":    .text("Yesterday"),
            "week":         .text("Last 7 days"),
            "older":        .text("Older"),
        ]
    )
}
