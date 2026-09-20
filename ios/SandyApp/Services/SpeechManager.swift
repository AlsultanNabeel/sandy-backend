import AVFoundation
import Combine
import Foundation

/// يقرأ ردود ساندي بالشات بصوتها: WAV اللي يرجّعه الخادم (صوت جيميني) بـ
/// `AVAudioPlayer`، ولو ما توفّر نرجع لصوت الجهاز الاحتياطي.
///
/// كان هون كمان استماع حيّ (`SFSpeechRecognizer`) وفم بيتحرّك على موجة الصوت.
/// المكالمة الحيّة صارت بـ `GeminiLiveManager`، فهداك النص ما حدا كان يناديه —
/// بس فمّه المنشور كان يتحدّث عشرين مرّة بالثانية، و`ChatView` ماسك هالكائن
/// كـ `@StateObject`، فكانت شاشة الشات كلها تنرسم من جديد طول ما ساندي تحكي.
/// لهيك ما في ولا خاصية منشورة هون، عن قصد.
@MainActor
final class SpeechManager: NSObject, ObservableObject {

    private let synth = AVSpeechSynthesizer()      // صوت احتياطي على الجهاز
    private var player: AVAudioPlayer?             // صوت جيميني الحقيقي

    /// يشغّل رد ساندي: صوت جيميني (`wav`) لو متاح، وإلا صوت الجهاز كاحتياط.
    func playReply(wav: Data?, fallbackText: String, localeID: String) {
        if let wav, playAudio(wav) { return }
        speakFallback(fallbackText, localeID: localeID)
    }

    /// يسكّت أي رد عم ينقرا.
    func stopSpeaking() {
        player?.stop()
        player = nil
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
    }

    private func playAudio(_ data: Data) -> Bool {
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? session.setActive(true)
        do {
            let p = try AVAudioPlayer(data: data)
            p.delegate = self
            p.prepareToPlay()
            player = p
            p.play()
            return true
        } catch {
            return false
        }
    }

    private func speakFallback(_ text: String, localeID: String) {
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { return }

        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? session.setActive(true)

        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
        let u = AVSpeechUtterance(string: clean)
        u.voice = bestVoice(for: localeID)
        u.rate = AVSpeechUtteranceDefaultSpeechRate
        u.pitchMultiplier = 1.05
        synth.speak(u)
    }

    private func bestVoice(for localeID: String) -> AVSpeechSynthesisVoice? {
        if let v = AVSpeechSynthesisVoice(language: localeID) { return v }
        let prefix = String(localeID.prefix(2))
        return AVSpeechSynthesisVoice.speechVoices().first { $0.language.hasPrefix(prefix) }
    }
}

// MARK: - نهاية صوت جيميني — نحرّر المشغّل

extension SpeechManager: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        let finished = ObjectIdentifier(player)
        Task { @MainActor in
            if let current = self.player, ObjectIdentifier(current) == finished {
                self.player = nil
            }
        }
    }
}
