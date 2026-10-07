import XCTest
@testable import SandyApp

/// M6: the call's sound failing to start left the socket open, the call bar up and the mic
/// taps on, so the next call put a second tap on the bus, which raises.
@MainActor
final class LiveCallAudioTests: XCTestCase {
    private final class FakeAudio: LiveAudio {
        var send: ((Data) -> Void)?
        var onMouth: ((CGFloat) -> Void)?
        var onSpeaking: ((Bool) -> Void)?
        var fails = false
        var stops = 0
        func start(duplex: Bool) throws {
            if fails { throw NSError(domain: "audio", code: 1) }
        }
        func stop() { stops += 1 }
        func enqueuePlayback(_ data: Data) {}
        func flushPlayback() {}
        func markEndTurn() {}
    }

    func testSoundThatDoesNotStartEndsTheWholeCall() {
        let audio = FakeAudio()
        audio.fails = true
        let call = GeminiLiveManager(audio: audio)
        call.handleText(#"{"type":"auth_ok","duplex":true}"#)
        XCTAssertEqual(audio.stops, 1, "what the failed start set up was left behind")
        XCTAssertFalse(call.inCall)
        XCTAssertEqual(call.phase, .idle)
        XCTAssertFalse(call.errorText.isEmpty)
    }
}
