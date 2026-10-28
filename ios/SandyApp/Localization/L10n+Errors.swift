import Foundation

// Namespace: errors — what the app says itself when a call fails (Core/Networking,
// Core/Auth, Core/Cache, Services/GeminiLiveManager). Read off the main thread too, through
// `L10nErrors.s`, which takes the app's language as `AppLocale.lang` sees it.
enum L10nErrors {
    static let ns = "errors"

    static func s(_ key: String) -> String { translate(AppLocale.lang, "\(ns).\(key)") }

    static let table = L10nTable(
        ar: [
            "sessionEnded": .text("انتهت الجلسة، سجّل دخولك من جديد."),
            "connection": .text("تعذّر الاتصال بالخادم. تأكد من الإنترنت وحاول مرة ثانية."),
            "badAddress": .text("عنوان غير صالح"),
            "unreadable": .text("تعذّر قراءة رد الخادم."),
            "code": .text("خطأ %@"),
            "generic": .text("خطأ"),
            "sorry": .text("معلش، صار خطأ."),
            "replyCut": .text("انقطع الرد قبل ما يكمل. جرّب مرة ثانية."),
            "chatNotCreated": .text("تعذّر إنشاء المحادثة"),
            "voiceUnavailable": .text("صوت غير متاح (%@)"),
            "imageFailed": .text("تعذّر توليد الصورة"),
            "imageEditFailed": .text("تعذّر تعديل الصورة"),
            "verifyFailed": .text("فشل التحقّق"),
            "googleVerifyFailed": .text("فشل التحقّق من جوجل"),
            "signupFailed": .text("فشل إنشاء الحساب"),
            "wrongCredentials": .text("بيانات الدخول غلط"),
            "googleMissing": .text("حزمة GoogleSignIn مش مضافة بالمشروع"),
            "googleWindow": .text("ما قدرنا نفتح نافذة جوجل"),
            "googleNoToken": .text("ما رجع توكن من جوجل"),
            "deviceNotSent": .text("الأمر ما وصل للجهاز. جرّب كمان شوي."),
            "liveAudioCut": .text("انقطع الصوت"),
            "liveConnectionLost": .text("انقطع الاتصال"),
            "liveAudioFailed": .text("ما قدرت أشغّل الصوت"),
        ],
        en: [
            "sessionEnded": .text("Your session ended, please sign in again."),
            "connection": .text("Couldn't reach the server. Check your internet and try again."),
            "badAddress": .text("Invalid address"),
            "unreadable": .text("Couldn't read the server's reply."),
            "code": .text("Error %@"),
            "generic": .text("Error"),
            "sorry": .text("Sorry, something went wrong."),
            "replyCut": .text("The reply was cut off before it finished. Try again."),
            "chatNotCreated": .text("Couldn't start the conversation"),
            "voiceUnavailable": .text("Voice unavailable (%@)"),
            "imageFailed": .text("Couldn't make the picture"),
            "imageEditFailed": .text("Couldn't edit the picture"),
            "verifyFailed": .text("Verification failed"),
            "googleVerifyFailed": .text("Google verification failed"),
            "signupFailed": .text("Couldn't create the account"),
            "wrongCredentials": .text("Wrong sign-in details"),
            "googleMissing": .text("The GoogleSignIn package isn't in the project"),
            "googleWindow": .text("Couldn't open the Google window"),
            "googleNoToken": .text("Google sent back no token"),
            "deviceNotSent": .text("The command didn't reach the device. Try again in a moment."),
            "liveAudioCut": .text("The audio dropped"),
            "liveConnectionLost": .text("The connection dropped"),
            "liveAudioFailed": .text("I couldn't start the audio"),
        ]
    )
}
