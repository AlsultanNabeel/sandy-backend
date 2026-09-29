import AVFoundation
import Combine
import Foundation

/// يقرأ ردود ساندي: WAV الخادم (جيميني) بـ `AVAudioPlayer`، وإلا صوت الجهاز.
/// ما في خاصية منشورة عن قصد: `ChatView` ماسكه كـ `@StateObject` وأي نشر بيعيد رسم الشات.
@MainActor
final class SpeechManager: NSObject, ObservableObject {

    private let synth = AVSpeechSynthesizer()
    private var player: AVAudioPlayer?

    func playReply(wav: Data?, fallbackText: String, localeID: String) {
        if let wav, playAudio(wav) { return }
        speakFallback(fallbackText, localeID: localeID)
    }

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

// MARK: - AVAudioPlayerDelegate

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
