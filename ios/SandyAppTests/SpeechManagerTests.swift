import XCTest
import AVFoundation
@testable import SandyApp

/// M8: reading a reply aloud during a live call switched the shared audio session to
/// playback, which silenced the call's mic.
@MainActor
final class SpeechManagerTests: XCTestCase {
    func testAReplyIsNotReadDuringALiveCall() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat)
        let speech = SpeechManager(callActive: { true })
        speech.playReply(wav: nil, fallbackText: "تمام، ضفتها", localeID: "ar-SA")
        XCTAssertEqual(session.category, .playAndRecord, "the call's audio session was taken for the reply")
        XCTAssertEqual(session.mode, .voiceChat)
    }
}
