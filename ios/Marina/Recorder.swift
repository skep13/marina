import AVFoundation

/// Hold-to-talk voice notes, recorded as AAC in .m4a for the bridge's Whisper.
@MainActor
final class Recorder: NSObject, ObservableObject {
    @Published var recording = false
    @Published var level: Float = 0

    private var recorder: AVAudioRecorder?
    private var meter: Timer?

    func start() async -> Bool {
        guard await AVAudioApplication.requestRecordPermission() else { return false }
        let session = AVAudioSession.sharedInstance()
        do {
            if !Audio.handsFreeOn {
                try session.setCategory(.playAndRecord, mode: .spokenAudio,
                                        options: [.defaultToSpeaker])
            }
            try session.setActive(true)
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("note-\(UUID().uuidString).m4a")
            let settings: [String: Any] = [
                AVFormatIDKey: kAudioFormatMPEG4AAC,
                AVSampleRateKey: 16_000,
                AVNumberOfChannelsKey: 1,
                AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue,
            ]
            let r = try AVAudioRecorder(url: url, settings: settings)
            r.isMeteringEnabled = true
            guard r.record() else { return false }
            recorder = r
            recording = true
            meter = Timer.scheduledTimer(withTimeInterval: 0.08, repeats: true) { [weak self] _ in
                Task { @MainActor in
                    guard let self, let r = self.recorder else { return }
                    r.updateMeters()
                    self.level = max(0, min(1, (r.averagePower(forChannel: 0) + 50) / 50))
                }
            }
            return true
        } catch {
            return false
        }
    }

    /// Stops and returns the clip, or nil if it was too short to mean anything.
    func stop() -> URL? {
        meter?.invalidate(); meter = nil
        guard let r = recorder else { recording = false; return nil }
        let duration = r.currentTime
        r.stop()
        recorder = nil
        recording = false
        level = 0
        Audio.playback()
        return duration >= 0.4 ? r.url : nil
    }

    func cancel() {
        if let url = stop() { try? FileManager.default.removeItem(at: url) }
    }
}

enum Audio {
    private(set) static var handsFreeOn = false

    /// Hands-free keeps the mic open alongside her voice, and keeps the app
    /// alive with the screen locked.
    static func handsFree(_ on: Bool) throws {
        handsFreeOn = on
        let session = AVAudioSession.sharedInstance()
        if on {
            try session.setCategory(.playAndRecord, mode: .default,
                                    options: [.defaultToSpeaker, .allowBluetoothA2DP])
            try session.setActive(true)
        } else {
            playback()
        }
    }

    /// Her voice plays even with the ring switch on silent, like a voice note.
    static func playback() {
        if handsFreeOn { return }
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio)
        try? session.setActive(true)
    }
}
