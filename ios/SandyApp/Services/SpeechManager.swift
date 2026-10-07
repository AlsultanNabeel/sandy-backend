import AVFoundation
import Combine
import Foundation

/// يقرأ ردود ساندي: WAV الخادم (جيميني) بـ `AVAudioPlayer`، وإلا صوت الجهاز.
/// ما في خاصية منشورة عن قصد: `ChatView` ماسكه كـ `@StateObject` وأي نشر بيعيد رسم الشات.
/// The audio session is the app's one: a reply is not read during a live call (switching it to
/// playback silenced the call's mic), and once read it is given back, so music ducked under it
/// comes back up.
@MainActor
final class SpeechManager: NSObject, ObservableObject {

    private let synth = AVSpeechSynthesizer()
    private var player: AVAudioPlayer?
    /// Whether a live call holds the audio session (a seam for tests).
    private let callActive: @MainActor () -> Bool

    init(callActive: @escaping @MainActor () -> Bool = { GeminiLiveManager.shared.inCall }) {
        self.callActive = callActive
        super.init()
        synth.delegate = self
    }

    func playReply(wav: Data?, fallbackText: String, localeID: String) {
        guard !callActive() else { return }
        if let wav, playAudio(wav) { return }
        speakFallback(fallbackText, localeID: localeID)
    }

    func stopSpeaking() {
        let was = player != nil || synth.isSpeaking
        player?.stop()
        player = nil
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
        if was { release() }
    }

    /// Done reading: the session goes back, and other apps' sound with it.
    private func release() {
        guard !callActive(), player == nil, !synth.isSpeaking else { return }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
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
                self.release()
            }
        }
    }
}

// MARK: - AVSpeechSynthesizerDelegate

extension SpeechManager: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.release() }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.release() }
    }
}
