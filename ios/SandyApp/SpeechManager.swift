import Foundation
import SwiftUI
import Speech
import AVFoundation

/// محرّك مكالمة ساندي الصوتية — يسمعك، يفكّر، ويرد بصوت **جيميني الحقيقي**، مع
/// مزامنة فمها على موجة الصوت (مخارج فعلية). يرجع يسمعك تلقائيًا بعد ما تخلص.
///
/// • الإدخال: `SFSpeechRecognizer` + `AVAudioEngine` يحوّلان كلامك لنص حيّ، وننهي
///   الجملة لحالنا لما تسكت ثانية وشوي (silence endpointing).
/// • الإخراج: نشغّل WAV اللي يرجّعه الخادم (صوت جيميني) بـ `AVAudioPlayer` مع قياس
///   الشدّة (metering) فنحرّك `mouthOpen` على موجتها. لو الصوت ما توفّر، نرجع لصوت
///   الجهاز الاحتياطي مع تحريك فم تقريبي.
/// • الحلقة: استماع ← (سكوت) ← تفكير (نداء الخادم) ← كلام بصوتها ← استماع من جديد.
@MainActor
final class SpeechManager: NSObject, ObservableObject {

    enum Phase { case idle, listening, thinking, speaking }
    @Published var phase: Phase = .idle
    /// النص الحيّ اللي عم نسمعه منك (يتصفّر مع كل دورة).
    @Published var transcript = ""
    /// انفتاح فم ساندي (صفر..واحد) — يتحرّك على موجة صوتها أثناء الكلام.
    @Published var mouthOpen: CGFloat = 0
    @Published var permissionDenied = false

    /// تُستدعى لما تخلص جملتك — الشاشة تبعتها للخادم وترجّع الصوت عبر `playReply`.
    var onFinalUtterance: ((String) -> Void)?

    private let audioEngine = AVAudioEngine()
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    private let synth = AVSpeechSynthesizer()      // صوت احتياطي على الجهاز
    private var player: AVAudioPlayer?             // صوت جيميني الحقيقي
    private var meterTimer: Timer?                 // يقرأ الشدّة → يحرّك الفم
    private var mouthOscTimer: Timer?              // تحريك فم تقريبي للاحتياطي

    private var liveActive = false
    private var liveLocaleID = "en-US"
    private var silenceTimer: Timer?
    private var lastChangeAt = Date()
    private let silenceLimit: TimeInterval = 1.2

    override init() {
        super.init()
        synth.delegate = self
    }

    // MARK: - المكالمة الحيّة

    func startLive(localeID: String) async {
        guard await requestAuth() else { return }
        liveActive = true
        liveLocaleID = localeID
        beginListening()
    }

    func endLive() {
        liveActive = false
        stopSilenceTimer()
        teardownAudio()
        stopSpeaking()
        phase = .idle
        transcript = ""
    }

    // MARK: - الأذونات

    private func requestAuth() async -> Bool {
        let speechOK = await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            SFSpeechRecognizer.requestAuthorization { status in
                cont.resume(returning: status == .authorized)
            }
        }
        let micOK = await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            AVAudioApplication.requestRecordPermission { granted in
                cont.resume(returning: granted)
            }
        }
        let ok = speechOK && micOK
        permissionDenied = !ok
        return ok
    }

    // MARK: - الاستماع (دورة واحدة)

    private func beginListening() {
        guard liveActive else { return }
        teardownAudio()
        transcript = ""

        let rec = SFSpeechRecognizer(locale: Locale(identifier: liveLocaleID))
        guard let rec, rec.isAvailable else { permissionDenied = true; phase = .idle; return }
        recognizer = rec

        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .measurement,
                                    options: [.duckOthers, .defaultToSpeaker])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch { phase = .idle; return }

        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        request = req

        let node = audioEngine.inputNode
        let format = node.outputFormat(forBus: 0)
        node.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            self?.request?.append(buffer)
        }
        audioEngine.prepare()
        do { try audioEngine.start() } catch { phase = .idle; return }

        phase = .listening
        lastChangeAt = Date()
        startSilenceTimer()

        task = rec.recognitionTask(with: req) { [weak self] result, _ in
            guard let self, let result else { return }
            Task { @MainActor in
                guard self.phase == .listening else { return }
                self.transcript = result.bestTranscription.formattedString
                self.lastChangeAt = Date()
            }
        }
    }

    // MARK: - إنهاء الجملة بالسكوت

    private func startSilenceTimer() {
        stopSilenceTimer()
        silenceTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.checkSilence() }
        }
    }

    private func stopSilenceTimer() {
        silenceTimer?.invalidate()
        silenceTimer = nil
    }

    private func checkSilence() {
        guard liveActive, phase == .listening else { return }
        guard !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        if Date().timeIntervalSince(lastChangeAt) > silenceLimit { endpoint() }
    }

    private func endpoint() {
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        stopSilenceTimer()
        teardownAudio()
        transcript = ""
        guard liveActive else { phase = .idle; return }
        if text.isEmpty { beginListening(); return }
        phase = .thinking
        onFinalUtterance?(text)
    }

    private func teardownAudio() {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        request?.endAudio()
        request = nil
        task?.cancel()
        task = nil
    }

    // MARK: - رد ساندي بصوتها (جيميني) + مزامنة الفم

    /// يشغّل رد ساندي: صوت جيميني (`wav`) لو متاح، وإلا صوت الجهاز كاحتياط.
    /// يحرّك الفم، وبعد ما يخلص يرجع يسمعك تلقائيًا (بالمكالمة الحيّة).
    func playReply(wav: Data?, fallbackText: String, localeID: String) {
        phase = .speaking
        if let wav, playAudio(wav) { return }       // صوت جيميني الحقيقي
        speakFallback(fallbackText, localeID: localeID)  // احتياطي على الجهاز
    }

    private func playAudio(_ data: Data) -> Bool {
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? session.setActive(true)
        do {
            let p = try AVAudioPlayer(data: data)
            p.isMeteringEnabled = true
            p.delegate = self
            p.prepareToPlay()
            player = p
            p.play()
            startMeterTimer()
            return true
        } catch {
            return false
        }
    }

    /// يقرأ شدّة الصوت كل لحظة ويحوّلها لانفتاح فم (مخارج فعلية).
    private func startMeterTimer() {
        stopMeterTimer()
        meterTimer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.updateMouthFromMeter() }
        }
    }

    private func stopMeterTimer() {
        meterTimer?.invalidate()
        meterTimer = nil
    }

    private func updateMouthFromMeter() {
        guard let p = player, p.isPlaying else { return }
        p.updateMeters()
        let db = p.averagePower(forChannel: 0)        // ~ -160..0
        // نطاق الكلام المعتاد (-45..-10 ديسيبل) → (صفر..واحد).
        let norm = max(0, min(1, (db + 45) / 35))
        withAnimation(.linear(duration: 0.05)) { mouthOpen = CGFloat(norm) }
    }

    // MARK: - الصوت الاحتياطي على الجهاز (لو ما توفّر صوت جيميني)

    private func speakFallback(_ text: String, localeID: String) {
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { finishSpeaking(); return }

        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? session.setActive(true)

        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
        let u = AVSpeechUtterance(string: clean)
        u.voice = bestVoice(for: localeID)
        u.rate = AVSpeechUtteranceDefaultSpeechRate
        u.pitchMultiplier = 1.05
        synth.speak(u)
        startMouthOscillation()       // ما في موجة → تحريك فم تقريبي
    }

    /// تحريك فم تقريبي للاحتياطي (بدون موجة فعلية).
    private func startMouthOscillation() {
        stopMouthOscillation()
        mouthOscTimer = Timer.scheduledTimer(withTimeInterval: 0.13, repeats: true) { [weak self] _ in
            Task { @MainActor in
                withAnimation(.easeInOut(duration: 0.12)) {
                    self?.mouthOpen = CGFloat.random(in: 0.2...0.85)
                }
            }
        }
    }

    private func stopMouthOscillation() {
        mouthOscTimer?.invalidate()
        mouthOscTimer = nil
    }

    // MARK: - إيقاف الكلام + إنهاء الدورة

    func stopSpeaking() {
        player?.stop()
        player = nil
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
        stopMeterTimer()
        stopMouthOscillation()
        mouthOpen = 0
    }

    /// خلصت ساندي تحكي — نقفل الفم ونرجع نسمعك (لو بمكالمة).
    private func finishSpeaking() {
        stopMeterTimer()
        stopMouthOscillation()
        withAnimation(.easeOut(duration: 0.15)) { mouthOpen = 0 }
        player = nil
        if liveActive { beginListening() } else { phase = .idle }
    }

    private func bestVoice(for localeID: String) -> AVSpeechSynthesisVoice? {
        if let v = AVSpeechSynthesisVoice(language: localeID) { return v }
        let prefix = String(localeID.prefix(2))
        return AVSpeechSynthesisVoice.speechVoices().first { $0.language.hasPrefix(prefix) }
    }
}

// MARK: - نهاية صوت جيميني (AVAudioPlayer)

extension SpeechManager: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in self.finishSpeaking() }
    }
}

// MARK: - نهاية الصوت الاحتياطي (AVSpeechSynthesizer)

extension SpeechManager: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) {
        Task { @MainActor in self.finishSpeaking() }
    }
    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel u: AVSpeechUtterance) {
        Task { @MainActor in
            self.stopMouthOscillation()
            self.mouthOpen = 0
            if !self.liveActive { self.phase = .idle }
        }
    }
}
