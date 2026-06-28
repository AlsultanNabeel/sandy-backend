import Foundation
import AVFoundation
import SwiftUI

/// مكالمة جيميني لايف الحيّة — نفس مسار الروبوت/الويب (`lib/voiceLive.js`):
/// نفتح ويب-سوكت `/voice`، نوثّق بتوكن المالك ({type:"hello", token})، نبثّ
/// صوت المايك ست عشرة كيلو (مونو، Int16)، ونشغّل صوتها أربعة وعشرين كيلو لحظيًا،
/// ونحرّك الفم على موجة صوتها الفعلية. نصف-مزدوج: نوقف المايك وهي بتحكي.
@MainActor
final class GeminiLiveManager: NSObject, ObservableObject {
    enum Phase: Equatable { case idle, connecting, listening, speaking }

    @Published var phase: Phase = .idle
    @Published var mouthOpen: CGFloat = 0
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
        ws?.cancel(with: .goingAway, reason: nil)
        ws = nil
        audio.stop()
        phase = .idle
        mouthOpen = 0
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
                self.phase = speaking ? .speaking : .listening
            }
        }
        receiveLoop()
    }

    private func receiveLoop() {
        ws?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure:
                Task { @MainActor in
                    guard !self.stopped else { return }
                    self.errorText = "انقطع الاتصال"
                    self.phase = .idle
                }
            case .success(let message):
                switch message {
                case .string(let text): Task { @MainActor in self.handleText(text) }
                case .data(let data):   self.audio.enqueuePlayback(data)
                @unknown default: break
                }
                self.receiveLoop()
            }
        }
    }

    private func handleText(_ text: String) {
        guard let d = text.data(using: .utf8),
              let m = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let type = m["type"] as? String else { return }
        switch type {
        case "auth_ok":
            do {
                try audio.start()
                phase = .listening
            } catch {
                errorText = "ما قدرت أشغّل الصوت"
                phase = .idle
            }
        case "end_turn":
            audio.markEndTurn()
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
private final class LiveAudioBridge {
    var send: ((Data) -> Void)?
    var onMouth: ((CGFloat) -> Void)?
    var onSpeaking: ((Bool) -> Void)?

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var converter: AVAudioConverter?
    private var sendFormat: AVAudioFormat?
    private let playFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                           sampleRate: 24000, channels: 1, interleaved: false)!

    private let lock = NSLock()
    private var speaking = false
    private var lastPlaybackAt = CFAbsoluteTimeGetCurrent() - 10
    private var pendingBuffers = 0
    private var started = false

    func start() throws {
        let s = AVAudioSession.sharedInstance()
        try s.setCategory(.playAndRecord, mode: .voiceChat,
                          options: [.defaultToSpeaker, .allowBluetooth])
        try s.setActive(true)

        let input = engine.inputNode
        let inFormat = input.outputFormat(forBus: 0)

        // رسم تشغيل ردّها.
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)

        // محوّل المايك → ست عشرة كيلو مونو Int16.
        let outFmt = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000,
                                   channels: 1, interleaved: true)
        sendFormat = outFmt
        if let outFmt { converter = AVAudioConverter(from: inFormat, to: outFmt) }

        // التقاط المايك (نصف-مزدوج: نسكت وهي بتحكي).
        input.installTap(onBus: 0, bufferSize: 2048, format: inFormat) { [weak self] buf, _ in
            self?.onMic(buf)
        }
        // موجة الخرج لتحريك الفم.
        engine.mainMixerNode.installTap(onBus: 0, bufferSize: 1024, format: nil) { [weak self] buf, _ in
            self?.onOutput(buf)
        }

        engine.prepare()
        try engine.start()
        player.play()
        started = true
    }

    func stop() {
        guard started else { return }
        started = false
        engine.inputNode.removeTap(onBus: 0)
        engine.mainMixerNode.removeTap(onBus: 0)
        player.stop()
        engine.stop()
    }

    // MARK: المايك → إرسال

    private func onMic(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        let sp = speaking
        let since = CFAbsoluteTimeGetCurrent() - lastPlaybackAt
        lock.unlock()
        // نصف-مزدوج: ما نبعت وهي بتحكي (أو بعدها بقليل) حتى ما يرجع صوتها للمايك.
        if sp || since < 0.4 { return }
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
        lastPlaybackAt = CFAbsoluteTimeGetCurrent()
        pendingBuffers += 1
        let wasSpeaking = speaking
        speaking = true
        lock.unlock()
        if !wasSpeaking { onSpeaking?(true) }

        player.scheduleBuffer(buf) { [weak self] in
            guard let self else { return }
            self.lock.lock()
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
        let dst = buf.floatChannelData![0]
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
        lock.lock(); let sp = speaking; lock.unlock()
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
