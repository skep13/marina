import AVFoundation
import Foundation

/// Hands-free: the mic stays open (the wireless mic's receiver, when it's
/// plugged in, or the phone's own), each stretch of speech is cut out and
/// sent to the bridge, and she answers only what's said to her: "Marina,
/// ..." or "..., Marina?". For a few seconds after she answers, anything
/// you say counts as talking to her, so a conversation doesn't need her
/// name every time.
///
/// It keeps running with the screen locked (the app's background audio
/// mode), which is also what lets her speak reminders out loud then. iOS
/// shows the orange mic dot the whole time it's on.
@MainActor
final class HandsFree: ObservableObject {
    enum State: Equatable { case off, listening, hearing, waiting }

    @Published private(set) var state: State = .off
    @Published private(set) var level: Float = 0
    @Published private(set) var input = ""        // which mic it's using
    @Published var problem: String?

    var on: Bool { state != .off }
    /// Set while she is thinking or talking, so she doesn't hear herself.
    var paused = false { didSet { if paused { phrase.reset() } } }
    /// Until when what you say counts as talking to her without her name.
    var followUntil = Date.distantPast
    var onPhrase: ((Data, Bool) -> Void)?

    private let engine = AVAudioEngine()
    private let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000,
                                       channels: 1, interleaved: true)!
    private var phrase = PhraseCutter()
    private var observers: [NSObjectProtocol] = []

    func start() async {
        guard !on else { return }
        guard await AVAudioApplication.requestRecordPermission() else {
            problem = "Marina needs the microphone for hands-free. Turn it on in Settings › Marina."
            return
        }
        do {
            try Audio.handsFree(true)
            try startEngine()
            state = .listening
            problem = nil
            watch()
        } catch {
            try? Audio.handsFree(false)
            problem = "Couldn't open the mic: \(error.localizedDescription)"
        }
    }

    func stop() {
        observers.forEach(NotificationCenter.default.removeObserver)
        observers = []
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        phrase.reset()
        state = .off
        level = 0
        try? Audio.handsFree(false)
    }

    private func startEngine() throws {
        let node = engine.inputNode
        node.removeTap(onBus: 0)
        let format = node.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw NSError(domain: "Marina", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "No microphone is available."])
        }
        guard let converter = AVAudioConverter(from: format, to: target) else {
            throw NSError(domain: "Marina", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "Can't read this microphone's audio."])
        }
        let target = self.target
        node.installTap(onBus: 0, bufferSize: 1600, format: format) { [weak self] buffer, _ in
            guard let pcm = Self.convert(buffer, with: converter, to: target) else { return }
            Task { @MainActor in self?.feed(pcm) }
        }
        engine.prepare()
        try engine.start()
        input = AVAudioSession.sharedInstance().currentRoute.inputs.first?.portName ?? "mic"
    }

    /// Phone calls and Siri take the mic; a mic plugged in or out changes
    /// its format. Either way, pick it back up.
    private func watch() {
        let center = NotificationCenter.default
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification,
                                            object: nil, queue: .main) { [weak self] note in
            let type = (note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt)
                .flatMap(AVAudioSession.InterruptionType.init)
            Task { @MainActor in
                guard let self, self.on, type == .ended else { return }
                self.restart()
            }
        })
        // Only a mic or headphones coming or going counts. Restarting changes
        // the route itself (category, preferred input), and reacting to that
        // looped forever and froze the app.
        observers.append(center.addObserver(forName: AVAudioSession.routeChangeNotification,
                                            object: nil, queue: .main) { [weak self] note in
            let reason = (note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt)
                .flatMap(AVAudioSession.RouteChangeReason.init)
            guard reason == .newDeviceAvailable || reason == .oldDeviceUnavailable else { return }
            Task { @MainActor in self?.scheduleRestart() }
        })
        observers.append(center.addObserver(forName: .AVAudioEngineConfigurationChange,
                                            object: engine, queue: .main) { [weak self] _ in
            Task { @MainActor in
                guard let self, !self.engine.isRunning else { return }
                self.scheduleRestart()
            }
        })
    }

    private var restartTask: Task<Void, Never>?
    private var lastRestart = Date.distantPast

    /// Several notifications arrive for one plug-in: restart once, after
    /// they settle, and never more than once a second.
    private func scheduleRestart() {
        guard on else { return }
        restartTask?.cancel()
        restartTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(400))
            guard let self, !Task.isCancelled, self.on,
                  Date().timeIntervalSince(self.lastRestart) > 1 else { return }
            self.lastRestart = Date()
            self.restart()
        }
    }

    private func restart() {
        engine.stop()
        do {
            try Audio.handsFree(true)
            try startEngine()
            problem = nil
        } catch {
            problem = "The mic went away: \(error.localizedDescription)"
        }
    }

    /// Runs on the audio thread: one buffer from the mic to 16 kHz mono.
    nonisolated private static func convert(_ buffer: AVAudioPCMBuffer, with converter: AVAudioConverter,
                                            to target: AVAudioFormat) -> [Int16]? {
        let ratio = 16_000 / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 32
        guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return nil }
        var fed = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if fed { status.pointee = .noDataNow; return nil }
            fed = true
            status.pointee = .haveData
            return buffer
        }
        guard error == nil, let data = out.int16ChannelData else { return nil }
        return Array(UnsafeBufferPointer(start: data[0], count: Int(out.frameLength)))
    }

    private func feed(_ samples: [Int16]) {
        guard on else { return }
        let event = phrase.feed(samples, paused: paused)
        // The meter needn't redraw the screen on every buffer.
        if abs(phrase.level - level) > 0.03 || phrase.level == 0 && level != 0 { level = phrase.level }
        switch event {
        case .started: state = .hearing
        case .ended(let clip):
            state = .waiting
            onPhrase?(Wav.make(clip, rate: 16_000), Date() < followUntil)
        case .dropped: state = .listening
        case nil: break
        }
    }

    /// The bridge has answered (or ignored) the last phrase.
    func ready() { if on { state = .listening } }
}

/// Finds where speech starts and stops in 16 kHz audio: an energy VAD with
/// a noise floor that follows the room, a little audio kept from before
/// speech starts so the first word isn't clipped, and a cap on length.
struct PhraseCutter {
    enum Event { case started, ended([Int16]), dropped }

    static let frame = 480                 // 30 ms
    var marginDB: Float = 10
    var minSpeechFrames = 7                // ~200 ms to count as speech
    var endSilenceFrames = 30              // ~900 ms of quiet ends a phrase
    var maxFrames = 500                    // 15 s
    var prerollFrames = 10                 // 300 ms

    private(set) var level: Float = 0
    private var floorDB: Float = -60
    private var pending: [Int16] = []
    private var preroll: [[Int16]] = []
    private var clip: [Int16] = []
    private var speaking = false
    private var loud = 0
    private var quiet = 0
    private var frames = 0

    mutating func reset() {
        pending = []; preroll = []; clip = []
        speaking = false; loud = 0; quiet = 0; frames = 0
    }

    mutating func feed(_ samples: [Int16], paused: Bool) -> Event? {
        pending += samples
        var out: Event?
        while pending.count >= Self.frame {
            let f = Array(pending.prefix(Self.frame))
            pending.removeFirst(Self.frame)
            if let e = step(f, paused: paused) { out = e }
        }
        return out
    }

    private mutating func step(_ f: [Int16], paused: Bool) -> Event? {
        var sum: Double = 0
        for s in f { let v = Double(s) / 32768; sum += v * v }
        let db = Float(10 * log10(sum / Double(f.count) + 1e-10))
        level = max(0, min(1, (db + 60) / 50))
        let isLoud = db > max(floorDB + marginDB, -50)

        if paused { return nil }

        if !speaking {
            // The room's noise: follow it down fast, up slowly.
            floorDB = db < floorDB ? 0.7 * floorDB + 0.3 * db : 0.995 * floorDB + 0.005 * db
            preroll.append(f)
            if preroll.count > prerollFrames + minSpeechFrames { preroll.removeFirst() }
            loud = isLoud ? loud + 1 : 0
            if loud >= minSpeechFrames {
                speaking = true
                clip = preroll.flatMap { $0 }
                preroll = []
                quiet = 0
                frames = loud
                return .started
            }
            return nil
        }

        clip += f
        frames += 1
        quiet = isLoud ? 0 : quiet + 1
        if quiet >= endSilenceFrames || frames >= maxFrames {
            let done = clip
            reset()
            // Under half a second of actual speech is a cough or a door.
            return frames - quiet < 16 && done.count < 16_000 ? .dropped : .ended(done)
        }
        return nil
    }
}

enum Wav {
    static func make(_ samples: [Int16], rate: Int) -> Data {
        var d = Data()
        func u32(_ v: UInt32) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 4)) }
        func u16(_ v: UInt16) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 2)) }
        let bytes = UInt32(samples.count * 2)
        d.append("RIFF".data(using: .ascii)!); u32(36 + bytes)
        d.append("WAVE".data(using: .ascii)!)
        d.append("fmt ".data(using: .ascii)!); u32(16); u16(1); u16(1)
        u32(UInt32(rate)); u32(UInt32(rate * 2)); u16(2); u16(16)
        d.append("data".data(using: .ascii)!); u32(bytes)
        samples.withUnsafeBufferPointer { d.append(Data(buffer: $0)) }
        return d
    }
}

/// Her voice without the avatar: for when the screen is off or the app is
/// in the background, where the avatar's page can't play sound.
@MainActor
final class NativeVoice: NSObject, AVAudioPlayerDelegate {
    private var player: AVAudioPlayer?
    private var done: CheckedContinuation<Void, Never>?

    /// Plays one sentence (base64 WAV from the bridge) and returns when it ends.
    func play(_ base64: String?) async {
        guard let base64, let data = Data(base64Encoded: base64),
              let p = try? AVAudioPlayer(data: data) else { return }
        stop()
        player = p
        p.delegate = self
        await withCheckedContinuation { c in
            done = c
            if !p.play() { finish() }
        }
    }

    func stop() {
        player?.stop()
        player = nil
        finish()
    }

    private func finish() {
        let c = done
        done = nil
        c?.resume()
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        // Only the clip still playing may end the wait: a late finish from the
        // "mm-hm" used to end the next sentence's wait early and cut it off.
        Task { @MainActor in if player === self.player { self.finish() } }
    }
}
