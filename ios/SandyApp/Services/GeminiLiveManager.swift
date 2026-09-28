import Foundation
import AVFoundation
import SwiftUI
import os

/// مكالمة جيميني لايف الحيّة عبر ويب-سوكت `/voice`: مايك ١٦ كيلو Int16، ردّها ٢٤ كيلو.
/// المايك بيضل مفتوح وهي بتحكي (مع إلغاء الصدى) حتى تقاطعها، لو السيرفر سمح بـ `duplex`.
@MainActor
final class GeminiLiveManager: NSObject, ObservableObject {
    enum Phase: Equatable { case idle, connecting, listening, speaking }

    /// Each transition plays a haptic and drives the call's Live Activity.
    @Published var phase: Phase = .idle {
        didSet {
            guard phase != oldValue else { return }
            switch phase {
            case .listening: Haptics.play(.listening)
            case .speaking:  Haptics.play(.speaking)
            case .idle, .connecting: break
            }
            CallLiveActivity.shared.phaseChanged(phase)
        }
    }
    @Published var mouthOpen: CGFloat = 0
    /// She is running a tool; the silence before her answer is work.
    @Published var working = false
    @Published var permissionDenied = false
    @Published var errorText = ""

    private var ws: URLSessionWebSocketTask?
    private var urlSession: URLSession?
    private let audio = LiveAudioBridge()
    private var stopped = false


    func start(baseURL: String, token: String) {
        stopped = false
        errorText = ""
        AVAudioApplication.requestRecordPermission { [weak self] granted in
            Task { @MainActor in
                guard let self, !self.stopped else { return }
                if !granted { self.permissionDenied = true; return }
                self.connect(baseURL: baseURL, token: token)
            }
        }
    }

    func stop() {
        stopped = true
        teardown()
    }

    /// Shared by user stop and a dropped connection, so a drop also releases mic and audio session.
    private func teardown() {
        ws?.cancel(with: .goingAway, reason: nil)
        ws = nil
        urlSession?.invalidateAndCancel()
        urlSession = nil
        audio.stop()
        phase = .idle
        mouthOpen = 0
        working = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }


    private func connect(baseURL: String, token: String) {
        guard let url = Self.wsURL(from: baseURL) else {
            errorText = "عنوان غير صالح"; return
        }
        phase = .connecting
        let session = URLSession(configuration: .default)
        urlSession = session
        let task = session.webSocketTask(with: url)
        ws = task
        task.resume()

        // تحية المالك (JWT) — يقابل HMAC تبع الجهاز.
        if let data = try? JSONSerialization.data(withJSONObject: ["type": "hello", "token": token]),
           let hello = String(data: data, encoding: .utf8) {
            task.send(.string(hello)) { _ in }
        }

        audio.send = { [weak task] frame in
            task?.send(.data(frame)) { _ in }
        }
        audio.onMouth = { [weak self] level in
            Task { @MainActor in self?.mouthOpen = level }
        }
        audio.onSpeaking = { [weak self] speaking in
            Task { @MainActor in
                guard let self, self.phase != .idle, self.phase != .connecting else { return }
                if speaking { self.working = false }
                self.phase = speaking ? .speaking : .listening
            }
        }
        receiveLoop()
    }

    private func receiveLoop() {
        guard let task = ws else { return }
        // Runs off the main actor: use the thread-safe audio bridge here, hop back to re-arm.
        let audio = self.audio
        task.receive { [weak self, weak task] result in
            guard let self else { return }
            switch result {
            case .failure:
                Task { @MainActor in
                    // A late failure from a previous socket must not end the call that replaced it.
                    guard !self.stopped, let task, task === self.ws else { return }
                    self.teardown()
                    self.errorText = "انقطع الاتصال"
                    Haptics.play(.failure)
                }
            case .success(let message):
                switch message {
                case .string(let text): Task { @MainActor in self.handleText(text) }
                case .data(let data):   audio.enqueuePlayback(data)
                @unknown default: break
                }
                Task { @MainActor in self.receiveLoop() }
            }
        }
    }

    private func handleText(_ text: String) {
        guard let d = text.data(using: .utf8),
              let m = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let type = m["type"] as? String else { return }
        switch type {
        case "auth_ok":
            // المايك مفتوح وهي بتحكي بس لمّا السيرفر يقول، حتى التراجع يصير من السيرفر.
            let duplex = (m["duplex"] as? Bool) ?? false
            do {
                try audio.start(duplex: duplex)
                phase = .listening
            } catch {
                errorText = "ما قدرت أشغّل الصوت"
                phase = .idle
            }
        case "end_turn":
            audio.markEndTurn()
            working = false
        case "interrupted":
            // قاطعتها: لازم تسكت هلّق، مش بعد ما يخلص اللي بالطابور.
            audio.flushPlayback()
            working = false
        case "working":
            working = true
        case "error":
            errorText = (m["msg"] as? String) ?? "خطأ"
        default:
            break
        }
    }

    static func wsURL(from baseURL: String) -> URL? {
        var s = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.hasPrefix("https") { s = "wss" + s.dropFirst(5) }
        else if s.hasPrefix("http") { s = "ws" + s.dropFirst(4) }
        while s.hasSuffix("/") { s.removeLast() }
        return URL(string: s + "/voice")
    }
}

// MARK: - جسر الصوت (خيوط الصوت اللحظية)

/// Unchecked Sendable: shared mutable state is guarded by `lock` (taps run on a real-time thread).
private final class LiveAudioBridge: @unchecked Sendable {
    /// Audio graph diagnostics (Console filter: SandyVoice); the server log can't see the phone.
    private static let log = Logger(subsystem: "com.sandy.app", category: "SandyVoice")

    var send: ((Data) -> Void)?
    var onMouth: ((CGFloat) -> Void)?
    var onSpeaking: ((Bool) -> Void)?

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var converter: AVAudioConverter?
    private var sendFormat: AVAudioFormat?
    /// Gemini sends 24 kHz mono float. Explicit failure instead of `!` so the crash log says which nil.
    private static func makePlayFormat() -> AVAudioFormat {
        guard let fmt = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                      sampleRate: 24000, channels: 1,
                                      interleaved: false) else {
            preconditionFailure("AVAudioFormat rejected 24 kHz mono float32")
        }
        return fmt
    }
    private let playFormat = LiveAudioBridge.makePlayFormat()

    private let lock = NSLock()
    /// Echo cancellation on: keep sending while she talks (lets you interrupt). Off: half-duplex.
    private var echoCancelled = false
    private var speaking = false
    private var lastPlaybackAt = CFAbsoluteTimeGetCurrent() - 10
    /// The echo canceller has heard least of a reply in its first moments.
    private var replyStartedAt = CFAbsoluteTimeGetCurrent() - 10
    private var pendingBuffers = 0
    /// Bumped by `flushPlayback`; completions of buffers from before a flush must not count down.
    private var generation = 0
    private var started = false
    private var configObserver: NSObjectProtocol?
    /// Logged once per reply: tells «no sound» apart from «sound going somewhere you can't hear».
    private var renderedThisReply = true

    func start(duplex: Bool) throws {
        let s = AVAudioSession.sharedInstance()
        try s.setCategory(.playAndRecord, mode: .voiceChat,
                          options: [.defaultToSpeaker, .allowBluetooth])
        try s.setActive(true)

        // إلغاء الصدى أول إشي بالمحرّك؛ تفعيله ع المدخل بيفعّله ع المخرج كمان.
        var cancelled = false
        if duplex {
            do {
                try engine.inputNode.setVoiceProcessingEnabled(true)
                cancelled = true
            } catch {
                cancelled = false  // نصف-مزدوج أحسن من صدى
            }
        }
        lock.lock(); echoCancelled = cancelled; lock.unlock()

        engine.attach(player)

        installMicTap()
        engine.mainMixerNode.installTap(onBus: 0, bufferSize: 1024, format: nil) { [weak self] buf, _ in
            self?.onOutput(buf)
        }

        connectOutput()
        engine.prepare()
        try engine.start()
        player.play()
        lock.lock(); started = true; lock.unlock()
        Self.log.notice("started: echoCancel=\(cancelled) \(self.describe(), privacy: .public)")

        // Resume after an interruption (call, Siri, alarm) instead of leaving a silent call open.
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: s, queue: .main
        ) { [weak self] note in
            self?.handleInterruption(note)
        }
        // تغيّر شكل الصوت (سمّاعة، إعادة ضبط) بيوقّف المحرّك وبيضل واقف.
        configObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange,
            object: engine, queue: .main
        ) { [weak self] _ in
            self?.handleConfigurationChange()
        }
    }

    /// Mono tap: with echo cancellation the input reports five channels and the converter
    /// returns silence; the engine downmixes, the converter only changes rate.
    private func installMicTap() {
        let input = engine.inputNode
        let hw = input.outputFormat(forBus: 0)
        guard hw.sampleRate > 0,
              let tapFmt = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                         sampleRate: hw.sampleRate, channels: 1,
                                         interleaved: false),
              let outFmt = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000,
                                         channels: 1, interleaved: true)
        else { return }
        sendFormat = outFmt
        converter = AVAudioConverter(from: tapFmt, to: outFmt)
        input.installTap(onBus: 0, bufferSize: 2048, format: tapFmt) { [weak self] buf, _ in
            self?.onMic(buf)
        }
    }

    /// Connect the output explicitly with its current format (redone on every config change):
    /// echo cancellation swaps in a voice-processing unit an implicit mixer link may not match.
    private func connectOutput() {
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        engine.connect(engine.mainMixerNode, to: engine.outputNode,
                       format: engine.outputNode.inputFormat(forBus: 0))
    }

    private func handleConfigurationChange() {
        lock.lock(); let live = started; lock.unlock()
        guard live else { return }
        Self.log.notice("configuration changed — rewiring: \(self.describe(), privacy: .public)")
        engine.inputNode.removeTap(onBus: 0)
        installMicTap()
        connectOutput()
        engine.prepare()
        if !engine.isRunning {
            do { try engine.start() } catch {
                Self.log.error("restart after configuration change failed: \(error.localizedDescription, privacy: .public)")
            }
        }
        player.play()
        Self.log.notice("rewired: \(self.describe(), privacy: .public)")
    }

    private func describe() -> String {
        let route = AVAudioSession.sharedInstance().currentRoute.outputs
            .map { $0.portType.rawValue }.joined(separator: ",")
        return "running=\(engine.isRunning) playing=\(player.isPlaying) "
            + "in=\(engine.inputNode.outputFormat(forBus: 0)) "
            + "mix=\(engine.mainMixerNode.outputFormat(forBus: 0)) "
            + "out=\(engine.outputNode.inputFormat(forBus: 0)) route=\(route)"
    }

    private var interruptionObserver: NSObjectProtocol?

    private func handleInterruption(_ note: Notification) {
        guard let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              AVAudioSession.InterruptionType(rawValue: raw) == .ended else { return }
        lock.lock(); let live = started; lock.unlock()
        guard live else { return }
        try? AVAudioSession.sharedInstance().setActive(true)
        if !engine.isRunning { try? engine.start() }
        player.play()
    }

    func stop() {
        lock.lock()
        let wasStarted = started
        started = false
        lock.unlock()
        guard wasStarted else { return }
        if let o = interruptionObserver {
            NotificationCenter.default.removeObserver(o)
            interruptionObserver = nil
        }
        if let o = configObserver {
            NotificationCenter.default.removeObserver(o)
            configObserver = nil
        }
        engine.inputNode.removeTap(onBus: 0)
        engine.mainMixerNode.removeTap(onBus: 0)
        player.stop()
        engine.stop()
    }


    private func onMic(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        let sp = speaking
        let duplex = echoCancelled
        let now = CFAbsoluteTimeGetCurrent()
        let sinceOut = now - lastPlaybackAt
        let intoReply = now - replyStartedAt
        lock.unlock()
        if duplex {
            // أول ربع ثانية من كل ردّ: إلغاء الصدى لسا ما سمع شي، وصدى أول كلمة ممكن ينحسب مقاطعة.
            if sp && intoReply < 0.25 { return }
        } else {
            // نصف-مزدوج: ما نبعت وهي بتحكي.
            if sp || sinceOut < 0.4 { return }
        }
        guard let frame = convertMic(buffer) else { return }
        send?(frame)
    }

    private func convertMic(_ input: AVAudioPCMBuffer) -> Data? {
        guard let converter, let outFmt = sendFormat else { return nil }
        let ratio = outFmt.sampleRate / input.format.sampleRate
        let capacity = AVAudioFrameCount(Double(input.frameLength) * ratio + 16)
        guard capacity > 0,
              let out = AVAudioPCMBuffer(pcmFormat: outFmt, frameCapacity: capacity) else { return nil }

        var fed = false
        var err: NSError?
        let status = converter.convert(to: out, error: &err) { _, outStatus in
            if fed { outStatus.pointee = .noDataNow; return nil }
            fed = true
            outStatus.pointee = .haveData
            return input
        }
        guard status != .error, out.frameLength > 0, let ch = out.int16ChannelData else { return nil }
        return Data(bytes: ch[0], count: Int(out.frameLength) * 2)
    }


    func enqueuePlayback(_ data: Data) {
        guard let buf = makeBuffer(data) else { return }
        lock.lock()
        // A frame in flight when `stop()` ran would `play()` a stopped engine, which raises.
        guard started else { lock.unlock(); return }
        lastPlaybackAt = CFAbsoluteTimeGetCurrent()
        pendingBuffers += 1
        let wasSpeaking = speaking
        if !wasSpeaking { replyStartedAt = lastPlaybackAt }
        speaking = true
        let gen = generation
        if !wasSpeaking { renderedThisReply = false }
        lock.unlock()
        if !wasSpeaking {
            onSpeaking?(true)
            Self.log.notice("reply arrived: \(self.describe(), privacy: .public)")
        }

        player.scheduleBuffer(buf) { [weak self] in
            guard let self else { return }
            self.lock.lock()
            // من ردّ انمسح بالمقاطعة.
            guard gen == self.generation else { self.lock.unlock(); return }
            self.pendingBuffers -= 1
            let drained = self.pendingBuffers <= 0
            if drained { self.speaking = false }
            self.lock.unlock()
            if drained {
                self.onSpeaking?(false)
                self.onMouth?(0)
            }
        }
        if !player.isPlaying { player.play() }
    }

    /// Drop everything queued so she goes quiet now, not at the end of the buffered sentence.
    func flushPlayback() {
        lock.lock()
        guard started else { lock.unlock(); return }
        generation &+= 1
        pendingBuffers = 0
        let was = speaking
        speaking = false
        lock.unlock()
        player.stop()
        player.play()
        if was { onSpeaking?(false) }
        onMouth?(0)
    }

    /// لو القائمة فاضية أصلًا نطفّي الكلام فورًا.
    func markEndTurn() {
        lock.lock()
        let drained = pendingBuffers <= 0
        if drained { speaking = false }
        lock.unlock()
        if drained { onSpeaking?(false); onMouth?(0) }
    }

    private func makeBuffer(_ data: Data) -> AVAudioPCMBuffer? {
        let frames = data.count / 2
        guard frames > 0,
              let buf = AVAudioPCMBuffer(pcmFormat: playFormat, frameCapacity: AVAudioFrameCount(frames))
        else { return nil }
        buf.frameLength = AVAudioFrameCount(frames)
        // Return nil rather than force: a future format change drops audio instead of crashing.
        guard let dst = buf.floatChannelData?[0] else { return nil }
        data.withUnsafeBytes { raw in
            let src = raw.bindMemory(to: Int16.self)
            for i in 0..<frames {
                dst[i] = max(-1, min(1, Float(Int16(littleEndian: src[i])) / 32768.0))
            }
        }
        return buf
    }


    private func onOutput(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        let sp = speaking
        let first = sp && !renderedThisReply
        if first { renderedThisReply = true }
        lock.unlock()
        if first { Self.log.notice("output is rendering her reply") }
        guard sp, let ch = buffer.floatChannelData else { return }
        let n = Int(buffer.frameLength)
        guard n > 0 else { return }
        let p = ch[0]
        var sum: Float = 0
        for i in 0..<n { sum += p[i] * p[i] }
        let rms = sqrt(sum / Float(n))
        // RMS → فتحة فم ٠..١.
        let level = CGFloat(min(1.0, max(0.0, rms * 7.0)))
        onMouth?(level)
    }
}
