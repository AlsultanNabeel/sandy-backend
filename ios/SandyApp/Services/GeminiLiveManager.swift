import Foundation
import AVFoundation
import SwiftUI
import os

/// مكالمة جيميني لايف الحيّة — نفس مسار الروبوت/الويب (`lib/voiceLive.js`):
/// نفتح ويب-سوكت `/voice`، نوثّق بتوكن المالك ({type:"hello", token})، نبثّ
/// صوت المايك ست عشرة كيلو (مونو، Int16)، ونشغّل صوتها أربعة وعشرين كيلو لحظيًا،
/// ونحرّك الفم على موجة صوتها الفعلية.
///
/// المايك بيضلّ مفتوح وهي بتحكي (مع إلغاء الصدى) — هيك بتقدر تقاطعها بصوتك زي
/// أي مساعد صوتي. السيرفر هو اللي بيقرّر بالمصافحة (`duplex`)، ولو قال لأ أو
/// فشل إلغاء الصدى، بنرجع نسكّر المايك وهي بتحكي.
@MainActor
final class GeminiLiveManager: NSObject, ObservableObject {
    enum Phase: Equatable { case idle, connecting, listening, speaking }

    /// Every real transition feels different (haptics) and drives the call's
    /// Live Activity / Dynamic Island: started on connecting, updated on each
    /// change, ended the moment the call goes idle (stop, error, drop).
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
    /// She is running a tool (a search, a reminder) — the seconds of silence
    /// before her answer are work, and the screen says so.
    @Published var working = false
    @Published var permissionDenied = false
    @Published var errorText = ""

    private var ws: URLSessionWebSocketTask?
    private var urlSession: URLSession?
    private let audio = LiveAudioBridge()
    private var stopped = false

    // MARK: - دورة الحياة

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

    /// Everything a finished call has to release — shared by a user stop and a
    /// dropped connection. A drop used to only set the error text: the mic kept
    /// capturing into a dead socket and the audio session stayed active until
    /// the sheet was closed.
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

    // MARK: - الويب-سوكت

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

        // إرسال إطارات المايك مباشرة عبر الـ task (آمن من أي خيط، بلا قفزة فاعل).
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
        // The receive callback runs off the main actor: take the audio bridge
        // (thread-safe, see LiveAudioBridge) here, and hop back to re-arm.
        let audio = self.audio
        task.receive { [weak self, weak task] result in
            guard let self else { return }
            switch result {
            case .failure:
                Task { @MainActor in
                    // A late failure from a previous socket must not end the
                    // call that replaced it.
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
            // المايك مفتوح وهي بتحكي بس لمّا السيرفر يقول — هيك التراجع
            // بيصير من إعدادات السيرفر بلا ما نبني التطبيق من جديد.
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
            // قاطعتها: جيميناي وقّف التوليد، وهون لازم تسكت **هلّق** — مش بعد
            // ما يخلص اللي بالطابور. بدون هاد بتكمّل جملة ما عاد إلها معنى.
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

    /// يحوّل عنوان الـ HTTP لـ ws/wss ويضيف /voice.
    static func wsURL(from baseURL: String) -> URL? {
        var s = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.hasPrefix("https") { s = "wss" + s.dropFirst(5) }
        else if s.hasPrefix("http") { s = "ws" + s.dropFirst(4) }
        while s.hasSuffix("/") { s.removeLast() }
        return URL(string: s + "/voice")
    }
}

// MARK: - جسر الصوت (يشتغل على خيوط الصوت اللحظية، خارج الفاعل الرئيسي)

/// يملك محرّك الصوت: التقاط المايك وتحويله لست عشرة كيلو Int16 وإرساله، وتشغيل
/// ردّها أربعة وعشرين كيلو، وقياس موجة الخرج لتحريك الفم. كل الحالة المشتركة
/// محميّة بقفل لأنّ نداءات الـ tap تجي من خيط لحظي.
/// Unchecked Sendable: every mutable field shared with the audio threads is
/// guarded by `lock`, and the engine/player are only driven from start/stop.
private final class LiveAudioBridge: @unchecked Sendable {
    /// What the audio graph actually did, in Xcode's console and Console.app
    /// (filter: SandyVoice). The phone is the one place the server's log cannot
    /// see into — «she changed to speaking and nothing came out» has four
    /// possible causes, and these lines say which one.
    private static let log = Logger(subsystem: "com.sandy.app", category: "SandyVoice")

    var send: ((Data) -> Void)?
    var onMouth: ((CGFloat) -> Void)?
    var onSpeaking: ((Bool) -> Void)?

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var converter: AVAudioConverter?
    private var sendFormat: AVAudioFormat?
    /// Gemini sends 24 kHz mono float. The initialiser is failable because
    /// AVAudioFormat rejects invalid combinations — these are literals it
    /// accepts, so the failure branch is unreachable. It is spelled out anyway:
    /// a `!` here crashes with "unexpectedly found nil" and no hint of which
    /// nil, while this crashes with the reason written in the log.
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
    /// Echo cancellation is on: keep sending while she talks — that is the
    /// whole of what lets you interrupt her. Off: half-duplex, as before.
    private var echoCancelled = false
    private var speaking = false
    private var lastPlaybackAt = CFAbsoluteTimeGetCurrent() - 10
    /// When the reply now playing began. The first moments of a reply are when
    /// the echo canceller has heard the least of it.
    private var replyStartedAt = CFAbsoluteTimeGetCurrent() - 10
    private var pendingBuffers = 0
    /// Bumped by `flushPlayback`. A buffer scheduled before a flush belongs to a
    /// reply that no longer exists; its completion must not count anything down.
    private var generation = 0
    private var started = false
    private var configObserver: NSObjectProtocol?
    /// Has the mixer rendered anything of the reply now playing? Logged once
    /// per reply: its absence is the difference between «no sound» and «sound
    /// going somewhere you cannot hear».
    private var renderedThisReply = true

    func start(duplex: Bool) throws {
        let s = AVAudioSession.sharedInstance()
        try s.setCategory(.playAndRecord, mode: .voiceChat,
                          options: [.defaultToSpeaker, .allowBluetooth])
        try s.setActive(true)

        // **إلغاء الصدى، قبل أي إشي تاني بالمحرّك.** النظام بيشيل صوت السمّاعة
        // من المايك، فمنقدر نضلّ نبعت وهي بتحكي. تفعيله ع المدخل بيفعّله ع
        // المخرج لحاله — بدّه التنين عشان يعرف شو طلع ليشيله من اللي دخل.
        var cancelled = false
        if duplex {
            do {
                try engine.inputNode.setVoiceProcessingEnabled(true)
                cancelled = true
            } catch {
                cancelled = false      // بنرجع لنصف-مزدوج — أحسن من صدى
            }
        }
        lock.lock(); echoCancelled = cancelled; lock.unlock()

        // رسم تشغيل ردّها (بيتوصّل بـ `connectOutput`).
        engine.attach(player)

        installMicTap()
        // موجة الخرج لتحريك الفم.
        engine.mainMixerNode.installTap(onBus: 0, bufferSize: 1024, format: nil) { [weak self] buf, _ in
            self?.onOutput(buf)
        }

        connectOutput()
        engine.prepare()
        try engine.start()
        player.play()
        lock.lock(); started = true; lock.unlock()
        Self.log.notice("started: echoCancel=\(cancelled) \(self.describe(), privacy: .public)")

        // The call keeps running with the screen locked (UIBackgroundModes:
        // audio). What can still stop it is an interruption — a phone call,
        // Siri, an alarm: the system halts the engine. Resume it when that ends
        // instead of leaving a silent call open.
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: s, queue: .main
        ) { [weak self] note in
            self?.handleInterruption(note)
        }
        // لمّا يتغيّر شكل الصوت (سمّاعة انوصلت، أو معالجة الصوت أعادت ضبط
        // المحرّك) المحرّك بيوقف وبيضلّ واقف. هاد بالضبط شكل «إطار واحد وسكت».
        configObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange,
            object: engine, queue: .main
        ) { [weak self] _ in
            self?.handleConfigurationChange()
        }
    }

    /// The microphone as one channel, at whatever rate the hardware runs.
    ///
    /// **With echo cancellation on, the input reports five channels and a
    /// different rate**, and an `AVAudioConverter` fed that format hands back
    /// silence — the call that sent one frame and then nothing. Asking the tap
    /// for mono makes the engine do the downmix, which is Apple's own advice;
    /// the converter below then only changes the rate.
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

    /// **The output, connected on purpose.**
    ///
    /// Echo cancellation swaps the engine's input/output for a voice-processing
    /// unit with its own format, and a link from the mixer to the output made
    /// implicitly — by whatever touched `mainMixerNode` first — is not
    /// guaranteed to match it. The symptom is exactly the report: the call goes
    /// to «speaking» (her audio arrived and was scheduled) and the mouth never
    /// moves (the mixer never rendered, so its tap never fired). Connecting it
    /// explicitly, with the format taken from the output as it is now, removes
    /// the guess — and it is redone after every configuration change.
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

    /// Formats, route and running state — everything the four causes differ in.
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

    // MARK: المايك → إرسال

    private func onMic(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        let sp = speaking
        let duplex = echoCancelled
        let now = CFAbsoluteTimeGetCurrent()
        let sinceOut = now - lastPlaybackAt
        let intoReply = now - replyStartedAt
        lock.unlock()
        if duplex {
            // أول ربع ثانية من كل ردّ بس: هون إلغاء الصدى لسا ما سمع شي من
            // هالردّ، وصدى أول كلمة ممكن ينحسب مقاطعة فتقطع حالها.
            if sp && intoReply < 0.25 { return }
        } else {
            // نصف-مزدوج: ما نبعت وهي بتحكي (أو بعدها بقليل).
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

    // MARK: تشغيل ردّها

    func enqueuePlayback(_ data: Data) {
        guard let buf = makeBuffer(data) else { return }
        lock.lock()
        // Frames arrive on the URLSession queue; one in flight when `stop()`
        // ran would call `play()` on a stopped engine, which raises.
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
            // من ردّ انمسح بالمقاطعة — مش إلنا نعدّ عليه.
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

    /// She was interrupted: drop everything queued so she goes quiet now, not
    /// at the end of the sentence already sitting in the buffer.
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

    /// الخادم أعلن نهاية الدور — لو القائمة فاضية أصلًا نطفّي الكلام فورًا.
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
        // Non-nil for a float format, which playFormat is. Returning nil rather
        // than forcing means a future format change drops audio instead of
        // killing the app mid-conversation.
        guard let dst = buf.floatChannelData?[0] else { return nil }
        data.withUnsafeBytes { raw in
            let src = raw.bindMemory(to: Int16.self)
            for i in 0..<frames {
                dst[i] = max(-1, min(1, Float(Int16(littleEndian: src[i])) / 32768.0))
            }
        }
        return buf
    }

    // MARK: موجة الخرج → الفم

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
        // خرائط RMS → فتحة فم ٠..١ (تكبير لطيف).
        let level = CGFloat(min(1.0, max(0.0, rms * 7.0)))
        onMouth?(level)
    }
}
