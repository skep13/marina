import SwiftUI
import UserNotifications

struct Message: Identifiable, Equatable {
    enum Role { case you, marina, note }
    let id = UUID()
    var role: Role
    var text: String
    var at = Date()
    var live = false        // still streaming in
    var unprompted = false  // she started it
}

struct Ask: Identifiable {
    let id: String
    let where_: String
    let text: String
}

/// The conversation: sends what you type or say to the bridge, shows her
/// reply as it streams, and hands each sentence to the avatar to speak.
@MainActor
final class Chat: ObservableObject {
    enum Link: Equatable { case unknown, ok(String), down(String) }

    @Published var messages: [Message] = []
    @Published var link: Link = .unknown
    @Published var busy = false
    @Published var activity: String?
    @Published var ask: Ask?
    @Published var voiceOn = Settings.voiceOn { didSet { Settings.voiceOn = voiceOn } }

    let avatar: AvatarController
    let recorder = Recorder()
    private var bridge: Bridge
    private var current: Task<Void, Never>?
    private var idleTask: Task<Void, Never>?
    private var chunksPlayed = 0
    private var generation = 0      // so a cancelled reply can't tidy up after the next one
    var foreground = true

    init(avatar: AvatarController) {
        self.avatar = avatar
        bridge = Bridge(baseURL: URL(string: Settings.bridgeURL), token: Settings.token)
    }

    // MARK: connection

    func reconfigure() {
        bridge.baseURL = URL(string: Settings.bridgeURL)
        bridge.token = Settings.token
        link = .unknown
        Task { await connect() }
    }

    func connect() async {
        do {
            let h = try await bridge.health()
            let model = h["model"] as? String ?? "ready"
            link = .ok(model)
            if messages.isEmpty { await loadHistory() }
            startIdle()
            Task { try? await bridge.post("warmup") }
        } catch {
            link = .down(Self.describe(error))
        }
    }

    private func loadHistory() async {
        guard let past = try? await bridge.history() else { return }
        let iso = ISO8601DateFormatter()
        messages = past.suffix(40).map { m in
            Message(role: m.role == "user" ? .you : .marina,
                    text: m.content,
                    at: m.at.flatMap { iso.date(from: $0) } ?? Date())
        }
    }

    /// While the app is open she can speak first: timers, follow-ups, openers.
    func startIdle() {
        guard idleTask == nil else { return }
        idleTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                if self.busy { try? await Task.sleep(for: .seconds(2)); continue }
                do {
                    var started = false
                    for try await ev in try self.bridge.idle() {
                        if ev.type == "disabled" { try? await Task.sleep(for: .seconds(60)); break }
                        guard ev.type == "chunk" else { continue }
                        if self.busy && !started { break }   // you got there first
                        if !started {
                            started = true
                            self.busy = true
                            self.messages.append(Message(role: .marina, text: "", live: true, unprompted: true))
                            if self.voiceOn && self.foreground { await self.avatar.begin() }
                        }
                        await self.take(ev)
                    }
                    if started { await self.finish(notify: true) }
                    try? await Task.sleep(for: .seconds(1.5))
                } catch {
                    if Task.isCancelled { return }
                    if case .ok = self.link { self.link = .down(Self.describe(error)) }
                    try? await Task.sleep(for: .seconds(8))
                    await self.connect()
                }
            }
        }
    }

    func stopIdle() { idleTask?.cancel(); idleTask = nil }

    // MARK: sending

    func send(_ text: String) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        interruptIfSpeaking()
        messages.append(Message(role: .you, text: text))
        run { try self.bridge.chat(text, speak: self.voiceOn) }
    }

    func sendVoice(_ file: URL) {
        interruptIfSpeaking()
        messages.append(Message(role: .you, text: "…", live: true))
        run { try self.bridge.voice(file) }
    }

    private func run(_ open: @escaping () throws -> AsyncThrowingStream<BridgeEvent, Error>) {
        current?.cancel()
        busy = true
        chunksPlayed = 0
        generation += 1
        let gen = generation
        current = Task {
            await avatar.unlockAudio()
            if voiceOn { await avatar.begin() }
            var started = false
            do {
                for try await ev in try open() {
                    if Task.isCancelled || gen != generation { break }
                    switch ev.type {
                    case "transcript":
                        if let i = messages.lastIndex(where: { $0.role == .you }) {
                            messages[i].text = ev.string("text") ?? ""
                            messages[i].live = false
                        }
                    case "cancelled":
                        if let i = messages.lastIndex(where: { $0.role == .you && $0.live }) { messages.remove(at: i) }
                        note(ev.string("message") ?? "Didn't catch that.")
                    case "chunk":
                        if !started {
                            started = true
                            messages.append(Message(role: .marina, text: "", live: true))
                        }
                        await take(ev)
                    case "activity":
                        activity = ev.string("text")
                    case "confirm":
                        ask = Ask(id: ev.string("id") ?? "", where_: ev.string("where") ?? "", text: ev.string("text") ?? "")
                    case "error":
                        note(ev.string("message") ?? "Something went wrong.")
                    default: break
                    }
                }
                if case .down = link { link = .unknown; Task { await connect() } }
            } catch {
                if !Task.isCancelled { note(Self.describe(error)); link = .down(Self.describe(error)) }
            }
            guard gen == generation else { return }
            if let i = messages.lastIndex(where: { $0.role == .you && $0.live }) { messages.remove(at: i) }
            await finish(notify: false)
        }
    }

    /// One sentence: add it to her bubble and give it to the avatar.
    private func take(_ ev: BridgeEvent) async {
        let text = ev.string("reply") ?? ev.string("speech") ?? ""
        if let i = messages.lastIndex(where: { $0.role == .marina && $0.live }) {
            messages[i].text = messages[i].text.isEmpty ? text : messages[i].text + " " + text
        }
        if let err = ev.string("error") { note(err) }
        chunksPlayed += 1
        if voiceOn && foreground { await avatar.chunk(ev) }
    }

    private func finish(notify: Bool) async {
        activity = nil
        if let i = messages.lastIndex(where: { $0.role == .marina && $0.live }) {
            messages[i].live = false
            if messages[i].text.isEmpty { messages.remove(at: i) }
            else if notify && !foreground && Settings.notifyOn { Notifier.post(messages[i].text) }
        }
        busy = false
        if voiceOn && foreground { await avatar.end() }
    }

    /// Typing over her cuts her off; only what she'd said gets saved.
    private func interruptIfSpeaking() {
        guard busy else { return }
        let said = chunksPlayed
        generation += 1
        current?.cancel()
        for i in messages.indices where messages[i].live {
            messages[i].live = false
            if messages[i].role == .marina, !messages[i].text.isEmpty { messages[i].text += " —" }
        }
        messages.removeAll { $0.text.isEmpty || ($0.role == .you && $0.text == "…") }
        Task {
            await avatar.stop()
            try? await bridge.post("interrupt", json: ["chunks": said])
        }
    }

    func stop() {
        interruptIfSpeaking()
        busy = false
        activity = nil
    }

    func answer(_ ok: Bool) {
        guard let ask else { return }
        self.ask = nil
        Task { try? await bridge.post("confirm", json: ["id": ask.id, "ok": ok]) }
    }

    func forget() {
        stop()
        Task {
            try? await bridge.post("reset")
            messages = []
            note("Conversation cleared. Her memories stay.")
        }
    }

    private func note(_ text: String) {
        messages.append(Message(role: .note, text: text))
    }

    static func describe(_ error: Error) -> String {
        if let e = error as? BridgeError { return e.localizedDescription }
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain {
            switch ns.code {
            case NSURLErrorTimedOut, NSURLErrorCannotConnectToHost, NSURLErrorCannotFindHost,
                 NSURLErrorNetworkConnectionLost, NSURLErrorNotConnectedToInternet:
                return "Can't reach lab3. Is Tailscale on?"
            default: break
            }
        }
        return error.localizedDescription
    }
}

enum Notifier {
    static func ask() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    static func post(_ text: String) {
        let content = UNMutableNotificationContent()
        content.title = "Marina"
        content.body = text
        content.sound = .default
        let req = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(req)
    }
}
