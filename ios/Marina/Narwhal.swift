import PhotosUI
import SwiftUI
import UIKit

/// Narwhal's side of Moonwake: the security and coding chat on lab3.
/// Sessions live on lab3 behind her bridge (/narwhal/sessions...), shared
/// with Narwhal.app on the Mac: either one lists, opens and continues the
/// same chats, and watches a reply live while the other one asked for it.
/// Each message goes to the abliterated security model or to KAT-Coder,
/// picked by the bridge (or by hand). Narwhal shares nothing with Marina.

// MARK: palette

enum Ops {
    static let ink = Color(hex: 0x17181C)       // page
    static let panel = Color(hex: 0x1E2025)     // sidebar, cards
    static let raised = Color(hex: 0x262A31)    // user bubble, chips
    static let code = Color(hex: 0x1F2227)
    static let line = Color(hex: 0x2C3038)
    static let text = Color(hex: 0xE6E8EC)
    static let dim = Color(hex: 0xA3A9B4)
    static let faint = Color(hex: 0x6F7682)
    static let tusk = Color(hex: 0x3ED2D3)      // accent, the security model
    static let tuskSoft = Color(hex: 0x173638)
    static let coder = Color(hex: 0xA594FF)     // KAT-Coder
    static let coderSoft = Color(hex: 0x2A2645)
    static let signal = Color(hex: 0xE3A43A)
    static let ok = Color(hex: 0x22A06B)
    static let alert = Color(hex: 0xFB923C)
    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
    static func routeColour(_ route: String?) -> Color { route == "code" ? coder : tusk }
    static func routeSoft(_ route: String?) -> Color { route == "code" ? coderSoft : tuskSoft }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255)
    }
}

/// The owner's narwhal logo (Assets: NarwhalLogo, a template image).
struct NarwhalMark: View {
    var colour: Color = Ops.tusk
    var body: some View {
        Image("NarwhalLogo").renderingMode(.template).resizable().scaledToFit().foregroundStyle(colour)
    }
}

// MARK: model

struct NarwhalSession: Identifiable, Equatable, Codable {
    var id: String
    var title: String
    var updated: String
    var running = false
    var lastRoute: String?

    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? ""
        title = d["title"] as? String ?? "New chat"
        updated = d["updated"] as? String ?? ""
        running = d["running"] as? Bool ?? false
        lastRoute = d["last_route"] as? String
    }

    var date: Date { ISO8601DateFormatter().date(from: updated) ?? .distantPast }
}

struct NarwhalTurn: Identifiable, Equatable, Codable {
    var id: String
    var role: String                 // "user" or "assistant"
    var text = ""
    var thinking = ""
    var route: String?
    var model: String?
    var label: String?
    var reason: String?
    var seconds: Double?
    var thinkSeconds: Double?
    var tokS: Double?
    var promptTokens: Int?
    var completionTokens: Int?
    var status = "ok"                // ok, running, error, stopped
    var error: String?
    var pending = false              // sent from here, not yet confirmed

    init(id: String, role: String, text: String = "") {
        self.id = id; self.role = role; self.text = text
    }

    init(_ d: [String: Any]) {
        func num(_ k: String) -> Double? { (d[k] as? NSNumber)?.doubleValue }
        id = d["id"] as? String ?? UUID().uuidString
        role = d["role"] as? String ?? "assistant"
        text = d["text"] as? String ?? ""
        thinking = d["thinking"] as? String ?? ""
        route = d["route"] as? String
        model = d["model"] as? String
        label = d["label"] as? String
        reason = d["reason"] as? String
        seconds = num("seconds")
        thinkSeconds = num("think_seconds")
        tokS = num("tok_s")
        promptTokens = num("prompt_tokens").map { Int($0) }
        completionTokens = num("completion_tokens").map { Int($0) }
        status = d["status"] as? String ?? "ok"
        error = d["error"] as? String
    }
}

/// Something the owner wants Narwhal to always know (projects, layouts,
/// addresses). Kept on lab3 and sent with every message, on both routes.
struct NarwhalNote: Identifiable, Equatable {
    var id: String
    var title: String
    var body: String
    var enabled: Bool
    var included: Bool               // on, and fits in the budget

    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? UUID().uuidString
        title = d["title"] as? String ?? "Untitled"
        body = d["body"] as? String ?? ""
        enabled = d["enabled"] as? Bool ?? true
        included = d["included"] as? Bool ?? enabled
    }

    var preview: String {
        body.split(separator: "\n").first { !$0.trimmingCharacters(in: .whitespaces).isEmpty }.map(String.init) ?? "Empty"
    }
}

@MainActor
final class NarwhalChat: ObservableObject {
    @Published var sessions: [NarwhalSession] = []
    @Published var current: String?
    @Published var turns: [NarwhalTurn] = []
    @Published var running = false
    @Published var liveID: String?
    @Published var online: Bool?
    @Published var problem: String?
    @Published var route = "auto"           // auto, security, code, claude
    // Claude Code on lab3: what it may do and which model, kept between launches.
    static let claudeModes = [("acceptEdits", "Edit files", "Edit"), ("bypassPermissions", "Edit + run commands", "Run"),
                              ("plan", "Plan only", "Plan")]
    static let claudeModels = [("", "Default"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"), ("fable", "Fable")]
    @Published var claudeMode = UserDefaults.standard.string(forKey: "narwhal.claudeMode") ?? "acceptEdits" {
        didSet { UserDefaults.standard.set(claudeMode, forKey: "narwhal.claudeMode") }
    }
    @Published var claudeModel = UserDefaults.standard.string(forKey: "narwhal.claudeModel") ?? "" {
        didSet { UserDefaults.standard.set(claudeModel, forKey: "narwhal.claudeModel") }
    }
    // lab3's own models: answer quickly (no thinking) or think first, and
    // whether they may search the web (SearXNG). Kept between launches.
    @Published var quick = UserDefaults.standard.bool(forKey: "narwhal.quick") {
        didSet { UserDefaults.standard.set(quick, forKey: "narwhal.quick") }
    }
    @Published var web = UserDefaults.standard.object(forKey: "narwhal.web") as? Bool ?? true {
        didSet { UserDefaults.standard.set(web, forKey: "narwhal.web") }
    }
    static let claudeEfforts = [("", "Auto"), ("low", "Low"), ("medium", "Medium"), ("high", "High"),
                                ("xhigh", "Extra high"), ("max", "Max")]
    @Published var claudeEffort = UserDefaults.standard.string(forKey: "narwhal.claudeEffort") ?? "" {
        didSet { UserDefaults.standard.set(claudeEffort, forKey: "narwhal.claudeEffort") }
    }
    /// The Claude plan's use as Claude Code last reported it: window name ->
    /// (fraction used, reset time).
    @Published var claudeUsage: [(name: String, used: Double, resets: Date?)] = []
    @Published var claudeUsageAt: Date?
    var claudeSummary: String {
        let mode = Self.claudeModes.first { $0.0 == claudeMode }?.2 ?? "Edit"
        var parts: [String] = []
        if let model = Self.claudeModels.first(where: { $0.0 == claudeModel && !$0.0.isEmpty })?.1 { parts.append(model) }
        if let e = Self.claudeEfforts.first(where: { $0.0 == claudeEffort && !$0.0.isEmpty })?.1 {
            parts.append(e == "Extra high" ? "XHigh" : e)
        }
        return (parts + [mode]).joined(separator: " · ")
    }
    /// The fullest plan window, for the ring on the chip.
    var claudeUsageTop: Double? { claudeUsage.map(\.used).max() }

    func setClaudeUsage(_ u: Any?) {
        guard let u = u as? [String: Any], let wins = u["windows"] as? [String: Any] else { return }
        let names = ["five_hour": "5-hour", "seven_day": "Week", "seven_day_opus": "Week · Opus", "seven_day_sonnet": "Week · Sonnet"]
        claudeUsage = wins.compactMap { k, v in
            guard let w = v as? [String: Any], let used = (w["used"] as? NSNumber)?.doubleValue else { return nil }
            let r = (w["resets"] as? NSNumber).map { Date(timeIntervalSince1970: $0.doubleValue) }
            return (names[k] ?? k.replacingOccurrences(of: "_", with: " "), used, r)
        }.sorted { $0.name.count < $1.name.count }
        claudeUsageAt = (u["at"] as? NSNumber).map { Date(timeIntervalSince1970: $0.doubleValue) }
    }

    // The owner's profile, kept on lab3 and shared with the Mac.
    static let profileColors: [UInt32] = [0x3ED2D3, 0xA594FF, 0xFB923C, 0x22A06B, 0xE3A43A, 0xF472B6, 0x60A5FA, 0xE6E8EC]
    @Published var profileName = UserDefaults.standard.string(forKey: "narwhal.profileName") ?? ""
    @Published var profileColor = UserDefaults.standard.string(forKey: "narwhal.profileColor") ?? "#3ed2d3"
    @Published var profilePhoto: UIImage? = UserDefaults.standard.data(forKey: "narwhal.profilePhoto").flatMap(UIImage.init(data:))

    private func applyProfile(_ r: [String: Any]) {
        profileName = r["name"] as? String ?? ""
        profileColor = r["color"] as? String ?? "#3ed2d3"
        let url = r["avatar"] as? String ?? ""
        let data = url.split(separator: ",", maxSplits: 1).last.flatMap { Data(base64Encoded: String($0)) }
        profilePhoto = url.isEmpty ? nil : data.flatMap(UIImage.init(data:))
        let d = UserDefaults.standard
        d.set(profileName, forKey: "narwhal.profileName"); d.set(profileColor, forKey: "narwhal.profileColor")
        d.set(url.isEmpty ? nil : data, forKey: "narwhal.profilePhoto")
    }

    func loadProfile() async {
        guard !demoMode else { return }
        if let r = try? await bridge.narwhalCall("narwhal/profile") as? [String: Any] { applyProfile(r) }
    }

    func saveProfile(_ change: [String: Any]) async {
        guard !demoMode else { return }
        do {
            if let r = try await bridge.narwhalCall("narwhal/profile", method: "PUT", body: change) as? [String: Any] { applyProfile(r) }
        } catch {
            problem = Chat.describe(error)
        }
    }

    /// A picked photo as a 160-point square JPEG data: URL.
    func savePhoto(_ image: UIImage) async {
        let side: CGFloat = 160
        let k = min(image.size.width, image.size.height)
        let r = UIGraphicsImageRenderer(size: CGSize(width: side, height: side), format: {
            let f = UIGraphicsImageRendererFormat(); f.scale = 1; return f }())
        let square = r.image { _ in
            let scale = side / k
            image.draw(in: CGRect(x: -(image.size.width - k) / 2 * scale, y: -(image.size.height - k) / 2 * scale,
                                  width: image.size.width * scale, height: image.size.height * scale))
        }
        guard let jpeg = square.jpegData(compressionQuality: 0.85) else { return }
        profilePhoto = square
        await saveProfile(["avatar": "data:image/jpeg;base64," + jpeg.base64EncodedString()])
    }

    func loadClaudeUsage() async {
        guard !demoMode else { return }
        if let r = try? await bridge.narwhalCall("narwhal/claude/usage") as? [String: Any] { setClaudeUsage(r["usage"]) }
    }
    @Published var context: [String: Int] = [:]
    @Published var liveFirstToken: Date?
    @Published var notes: [NarwhalNote] = []
    @Published var notesUsed = 0
    @Published var notesMax = 12_000
    static let noteMax = 8_000

    private var seq = 0
    private var followTask: Task<Void, Never>?
    private var watchTask: Task<Void, Never>?
    private var refreshTask: Task<Void, Never>?
    private var demoMode = false

    private var bridge: Bridge { Bridge(baseURL: URL(string: Settings.bridgeURL), token: Settings.token) }

    private static var dir: URL {
        let d = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    init() {
        // Shown at once (and when lab3 is out of reach) until the bridge answers.
        if let data = try? Data(contentsOf: Self.dir.appendingPathComponent("narwhal-sessions.json")),
           let saved = try? JSONDecoder().decode([NarwhalSession].self, from: data) {
            sessions = saved
        }
    }

    // --- connecting --------------------------------------------------------

    /// Called when the app comes to the front: follow the session list (and
    /// the open chat) live.
    func connect() {
        guard !demoMode else { return }
        if watchTask == nil {
            watchTask = Task { [weak self] in await self?.watchLoop() }
        }
        if let current, followTask == nil { follow(current) }
        Task { await importOldChat(); await refresh() }
    }

    /// Called when the app goes to the back: iOS would cut the streams anyway.
    /// Replies keep running on lab3.
    func disconnect() {
        watchTask?.cancel(); watchTask = nil
        followTask?.cancel(); followTask = nil
    }

    private func watchLoop() async {
        var delay: UInt64 = 1
        while !Task.isCancelled {
            do {
                for try await ev in try bridge.narwhalStream("narwhal/watch") {
                    delay = 1
                    if ev.type == "hello" { online = true; await refresh(); await loadNotes(); await loadClaudeUsage(); await loadProfile(); continue }
                    if ev.type == "profile" { await loadProfile(); continue }
                    if ev.type == "notes" { await loadNotes(); continue }
                    if ev.type == "claude_usage" { setClaudeUsage(ev.raw["usage"]); continue }
                    guard ev.type == "changed" else { continue }
                    if ev.raw["deleted"] as? Bool == true, ev.string("session") == current { newChat() }
                    scheduleRefresh()
                }
            } catch {
                if Task.isCancelled { return }
                online = false
                problem = Chat.describe(error)
            }
            try? await Task.sleep(nanoseconds: delay * 1_000_000_000)
            delay = min(delay * 2, 15)
        }
    }

    private func scheduleRefresh() {
        refreshTask?.cancel()
        refreshTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 150_000_000)
            if !Task.isCancelled { await self?.refresh() }
        }
    }

    func refresh() async {
        guard !demoMode else { return }
        do {
            let r = try await bridge.narwhalCall("narwhal/sessions") as? [String: Any]
            sessions = (r?["sessions"] as? [[String: Any]] ?? []).map(NarwhalSession.init)
            online = true
            problem = nil
            if let data = try? JSONEncoder().encode(sessions) {
                try? data.write(to: Self.dir.appendingPathComponent("narwhal-sessions.json"), options: .atomic)
            }
        } catch {
            online = false
            problem = Chat.describe(error)
        }
    }

    /// The chat this phone kept on its own before sessions moved to lab3
    /// goes up once, as its own session.
    private var importing = false

    private func importOldChat() async {
        // connect() runs at launch and on every return to the front: only
        // one import may run, and the file moves away once it's done.
        guard !importing else { return }
        importing = true
        defer { importing = false }
        let old = Self.dir.appendingPathComponent("narwhal.json")
        guard let data = try? Data(contentsOf: old),
              let turns = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]], !turns.isEmpty
        else { return }
        let body = turns.map { t -> [String: Any] in
            var o: [String: Any] = ["role": t["role"] ?? "user", "text": t["text"] ?? ""]
            if let v = t["thinking"] { o["thinking"] = v }
            if let v = t["seconds"] { o["seconds"] = v }
            if let v = t["thinkSeconds"] { o["think_seconds"] = v }
            if let v = t["failed"] { o["failed"] = v }
            return o
        }
        do {
            _ = try await bridge.narwhalCall("narwhal/sessions/import", method: "POST",
                                             body: ["title": "Chat from the phone", "turns": body])
            try? FileManager.default.moveItem(at: old, to: Self.dir.appendingPathComponent("narwhal.imported.json"))
        } catch {}
    }

    // --- one session --------------------------------------------------------

    func open(_ id: String) {
        guard !demoMode else { current = id; return }
        followTask?.cancel(); followTask = nil
        current = id
        turns = []
        running = false
        liveID = nil
        Task {
            do {
                try await load(id)
                follow(id)
            } catch {
                problem = Chat.describe(error)
            }
        }
    }

    private func load(_ id: String) async throws {
        guard let s = try await bridge.narwhalCall("narwhal/sessions/\(id)") as? [String: Any], current == id else { return }
        turns = (s["turns"] as? [[String: Any]] ?? []).map(NarwhalTurn.init)
        seq = (s["seq"] as? NSNumber)?.intValue ?? 0
        running = s["running"] as? Bool ?? false
        context = s["context"] as? [String: Int] ?? context
        liveID = running ? turns.last?.id : nil
        liveFirstToken = running && !(turns.last?.text.isEmpty ?? true) ? Date() : nil
    }

    private func follow(_ id: String) {
        followTask?.cancel()
        followTask = Task { [weak self] in
            var delay: UInt64 = 1
            while !Task.isCancelled {
                guard let self, self.current == id else { return }
                do {
                    let stream = try self.bridge.narwhalStream("narwhal/sessions/\(id)/follow",
                                                               query: [URLQueryItem(name: "after", value: String(self.seq))])
                    for try await ev in stream {
                        guard self.current == id else { return }
                        delay = 1
                        await self.take(ev)
                    }
                } catch {
                    if Task.isCancelled { return }
                }
                try? await Task.sleep(nanoseconds: delay * 1_000_000_000)
                delay = min(delay * 2, 15)
            }
        }
    }

    private func take(_ ev: BridgeEvent) async {
        if let s = ev.int("seq") { seq = s }
        let turnID = ev.string("turn_id")
        switch ev.type {
        case "resync":
            if let current { try? await load(current) }
        case "user":
            guard let d = ev.raw["turn"] as? [String: Any] else { return }
            let t = NarwhalTurn(d)
            turns.removeAll { $0.pending }
            if !turns.contains(where: { $0.id == t.id }) { turns.append(t) }
        case "start":
            guard let turnID else { return }
            var t = NarwhalTurn(id: turnID, role: "assistant")
            t.route = ev.string("route"); t.model = ev.string("model")
            t.label = ev.string("label"); t.reason = ev.string("reason"); t.status = "running"
            if let c = ev.int("context"), let r = t.route { context[r] = c }
            if let i = turns.firstIndex(where: { $0.id == turnID }) { turns[i] = t } else { turns.append(t) }
            running = true
            liveID = turnID
            liveFirstToken = nil
        case "think", "text":
            guard let i = turns.firstIndex(where: { $0.id == turnID }) else { return }
            liveFirstToken = liveFirstToken ?? Date()
            if ev.type == "think" { turns[i].thinking += ev.string("text") ?? "" }
            else { turns[i].text += ev.string("text") ?? "" }
        case "done", "stopped", "error":
            if let d = ev.raw["turn"] as? [String: Any], let i = turns.firstIndex(where: { $0.id == turnID }) {
                turns[i] = NarwhalTurn(d)
            }
            running = false
            liveID = nil
            liveFirstToken = nil
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
        default: break
        }
    }

    // --- actions -------------------------------------------------------------

    func send(_ raw: String) {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !running else { return }
        if demoMode { demoReply(text); return }
        var pending = NarwhalTurn(id: "pending-\(UUID().uuidString)", role: "user", text: text)
        pending.pending = true
        turns.append(pending)
        Task {
            do {
                var id = current
                if id == nil {
                    let s = try await bridge.narwhalCall("narwhal/sessions", method: "POST", body: [:]) as? [String: Any]
                    id = s?["id"] as? String
                    guard let id else { return }
                    current = id
                    seq = 0
                    follow(id)
                }
                guard let id else { return }
                var body: [String: Any] = ["text": text, "route": route]
                if route == "claude" { body["mode"] = claudeMode; body["model"] = claudeModel; body["effort"] = claudeEffort }
                else { body["think"] = quick ? "quick" : "think"; body["web"] = web }
                _ = try await bridge.narwhalCall("narwhal/sessions/\(id)/messages", method: "POST", body: body)
            } catch {
                turns.removeAll { $0.id == pending.id }
                let busy = (error as? NarwhalError)?.status == 409
                problem = busy ? "Narwhal is still answering in this chat." : Chat.describe(error)
            }
        }
    }

    func stop() {
        guard let current, running else { return }
        if demoMode { running = false; liveID = nil; return }
        Task { _ = try? await bridge.narwhalCall("narwhal/sessions/\(current)/stop", method: "POST") }
    }

    func newChat() {
        followTask?.cancel(); followTask = nil
        current = nil
        turns = []
        running = false
        liveID = nil
    }

    func delete(_ id: String) {
        if id == current { newChat() }
        sessions.removeAll { $0.id == id }
        Task { _ = try? await bridge.narwhalCall("narwhal/sessions/\(id)", method: "DELETE"); await refresh() }
    }

    func rename(_ id: String, _ title: String) {
        let t = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        if let i = sessions.firstIndex(where: { $0.id == id }) { sessions[i].title = t }
        Task { _ = try? await bridge.narwhalCall("narwhal/sessions/\(id)", method: "PATCH", body: ["title": t]) }
    }

    func retry(_ turn: NarwhalTurn) {
        guard let i = turns.firstIndex(of: turn),
              let q = turns[..<i].last(where: { $0.role == "user" }) else { return }
        send(q.text)
    }

    // --- notes ---------------------------------------------------------------

    func loadNotes() async {
        guard !demoMode else { return }
        do {
            let r = try await bridge.narwhalCall("narwhal/notes") as? [String: Any]
            notes = (r?["notes"] as? [[String: Any]] ?? []).map(NarwhalNote.init)
            notesUsed = (r?["used_chars"] as? NSNumber)?.intValue ?? 0
            notesMax = (r?["max_chars"] as? NSNumber)?.intValue ?? 12_000
        } catch {
            problem = Chat.describe(error)
        }
    }

    func addNote() async -> NarwhalNote? {
        if demoMode {
            let n = NarwhalNote(["id": UUID().uuidString, "title": "Untitled", "body": ""])
            notes.append(n); return n
        }
        do {
            let d = try await bridge.narwhalCall("narwhal/notes", method: "POST", body: ["title": "Untitled", "body": ""])
            guard let d = d as? [String: Any] else { return nil }
            let n = NarwhalNote(d)
            notes.append(n)
            return n
        } catch {
            problem = "Couldn't add a note: " + Chat.describe(error)
            return nil
        }
    }

    /// Saves a note's text or switches it on/off. Returns false if it failed.
    @discardableResult
    func saveNote(_ id: String, title: String? = nil, body: String? = nil, enabled: Bool? = nil) async -> Bool {
        var patch: [String: Any] = [:]
        if let title { patch["title"] = title.trimmingCharacters(in: .whitespaces).isEmpty ? "Untitled" : title }
        if let body { patch["body"] = body }
        if let enabled { patch["enabled"] = enabled }
        if demoMode {
            if let i = notes.firstIndex(where: { $0.id == id }) {
                if let t = patch["title"] as? String { notes[i].title = t }
                if let body { notes[i].body = body }
                if let enabled { notes[i].enabled = enabled; notes[i].included = enabled }
            }
            return true
        }
        do {
            let d = try await bridge.narwhalCall("narwhal/notes/\(id)", method: "PATCH", body: patch)
            if let d = d as? [String: Any], let i = notes.firstIndex(where: { $0.id == id }) {
                let included = notes[i].included
                notes[i] = NarwhalNote(d)
                notes[i].included = included        // the listing says; it comes with the watch event
            }
            return true
        } catch {
            problem = "Couldn't save the note: " + Chat.describe(error)
            return false
        }
    }

    func deleteNote(_ id: String) {
        notes.removeAll { $0.id == id }
        guard !demoMode else { return }
        Task {
            do { _ = try await bridge.narwhalCall("narwhal/notes/\(id)", method: "DELETE") }
            catch { problem = "Couldn't delete the note: " + Chat.describe(error) }
            await loadNotes()
        }
    }

    // --- the meter -------------------------------------------------------------

    var title: String { sessions.first { $0.id == current }?.title ?? (current == nil ? "New chat" : "") }

    /// Context used: the last finished answer's prompt + reply tokens (exact,
    /// from llama-server), plus an estimate for what is streaming now.
    var contextUsed: (used: Int, window: Int, estimated: Bool) {
        let doneIndex = turns.lastIndex { $0.role == "assistant" && ($0.promptTokens ?? 0) + ($0.completionTokens ?? 0) > 0 }
        var used = 0
        if let i = doneIndex { used = (turns[i].promptTokens ?? 0) + (turns[i].completionTokens ?? 0) }
        let after = turns[((doneIndex ?? -1) + 1)...]
        let extra = after.reduce(0) { $0 + ($1.text.count + $1.thinking.count) / 4 }
        let r = turns.last { $0.id == liveID }?.route ?? (route != "auto" ? route : turns.last { $0.role == "assistant" }?.route ?? "security")
        return (used + extra, context[r] ?? 131_072, extra > 0 || doneIndex == nil)
    }

    var speed: String? {
        if let id = liveID, let first = liveFirstToken, let t = turns.first(where: { $0.id == id }) {
            let secs = Date().timeIntervalSince(first)
            guard secs > 0.5 else { return nil }
            let rate = Double(t.text.count + t.thinking.count) / 4 / secs
            return "~\(rate >= 10 ? String(Int(rate)) : String(format: "%.1f", rate)) tok/s"
        }
        return turns.last { $0.role == "assistant" && $0.tokS != nil }?.tokS.map { String(format: "%.1f tok/s", $0) }
    }

    // --- demo --------------------------------------------------------------

    #if DEBUG
    /// For looking at the screen in the simulator: `-demoNarwhal`.
    func demo() {
        demoMode = true
        online = true
        let now = ISO8601DateFormatter().string(from: Date())
        let old = ISO8601DateFormatter().string(from: Date().addingTimeInterval(-86_400 * 3))
        sessions = [
            NarwhalSession(["id": "a", "title": "SMB enumeration on the lab subnet", "updated": now, "last_route": "security"]),
            NarwhalSession(["id": "b", "title": "Refactor the port scanner into async", "updated": now, "last_route": "code", "running": true]),
            NarwhalSession(["id": "c", "title": "Kerberoasting detection in Sentinel", "updated": old]),
        ]
        current = "a"
        context = ["security": 131_072, "code": 131_072]
        var u = NarwhalTurn(id: "u1", role: "user", text: "How do I enumerate SMB shares on 10.0.4.12 without creds?")
        u.status = "ok"
        var a = NarwhalTurn(id: "a1", role: "assistant",
                            text: "Start with what a null session gives you.\n\n### 1. List shares\n```bash\nsmbclient -N -L //10.0.4.12\nnxc smb 10.0.4.12 -u '' -p '' --shares\n```\n\n| Share | Null | Guest |\n|---|---|---|\n| `IPC$` | read | read |\n| `Users` | – | read |\n\nIf **signing is disabled**, relaying is your next step.")
        a.thinking = "Null session first, then guest. List shares, then RID cycling."
        a.route = "security"; a.label = "Narwhal · abliterated"; a.seconds = 21.4; a.thinkSeconds = 6
        a.tokS = 24.6; a.promptTokens = 1840; a.completionTokens = 412
        var u2 = NarwhalTurn(id: "u2", role: "user", text: "Now write a Python script that does that for a list of hosts")
        u2.status = "ok"
        var live = NarwhalTurn(id: "a2", role: "assistant", text: "Here's a small wrapper around `nxc`:\n\n```python\nimport subprocess\n\ndef shares(host):\n    out = subprocess.run([\"nxc\", \"smb\", host")
        live.thinking = "Loop hosts, call nxc, parse the share table."
        live.route = "code"; live.label = "KAT-Coder"; live.status = "running"
        turns = [u, a, u2, live]
        notes = [
            NarwhalNote(["id": "n1", "title": "Homelab", "included": true,
                         "body": "lab3   192.168.1.15   Proxmox, llama-swap :8080\nlab2   192.168.1.131  Mint desktop\nTailscale: lab3 100.82.175.98"]),
            NarwhalNote(["id": "n2", "title": "Narwhal repo", "included": true,
                         "body": "~/narwhal\n  app/       Rust Mac app\n  songbird/  security model + RAG\n  forge/     coding agent"]),
            NarwhalNote(["id": "n3", "title": "Old CTF box", "enabled": false, "body": "10.10.11.42, retired"]),
        ]
        notesUsed = 412
        running = true
        liveID = "a2"
        liveFirstToken = Date().addingTimeInterval(-3)
    }

    private func demoReply(_ text: String) {
        var u = NarwhalTurn(id: UUID().uuidString, role: "user", text: text)
        u.status = "ok"
        turns.append(u)
    }
    #else
    private func demoReply(_ text: String) {}
    #endif
}

// MARK: screen

struct NarwhalView: View {
    @EnvironmentObject var narwhal: NarwhalChat
    @State private var draft = ""
    @State private var drawer = false
    @State private var notesOpen = false
    @FocusState private var focused: Bool

    var body: some View {
        ZStack(alignment: .leading) {
            NarwhalBackdrop().ignoresSafeArea()
            VStack(spacing: 0) {
                NarwhalTopBar(drawer: $drawer)
                if narwhal.current == nil && narwhal.turns.isEmpty {
                    NarwhalEmpty(draft: $draft, focused: $focused)
                } else {
                    NarwhalLog()
                }
                NarwhalComposer(draft: $draft, focused: $focused)
            }
            if let p = narwhal.problem {
                Text(p).font(.system(size: 13, weight: .medium)).foregroundStyle(Ops.ink)
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .background(Ops.text, in: Capsule())
                    .frame(maxWidth: .infinity).padding(.top, 52)
                    .frame(maxHeight: .infinity, alignment: .top)
                    .onTapGesture { narwhal.problem = nil }
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .task(id: p) { try? await Task.sleep(for: .seconds(4)); narwhal.problem = nil }
            }
            if drawer {
                Color.black.opacity(0.45).ignoresSafeArea()
                    .onTapGesture { withAnimation(.easeOut(duration: 0.22)) { drawer = false } }
                    .transition(.opacity)
                NarwhalDrawer(drawer: $drawer, notesOpen: $notesOpen)
                    .transition(.move(edge: .leading))
            }
        }
        .animation(.easeOut(duration: 0.2), value: narwhal.problem)
        .sheet(isPresented: $notesOpen) {
            NarwhalNotesView().environmentObject(narwhal)
        }
        .gesture(DragGesture(minimumDistance: 24).onEnded { g in
            // Swipe right from the left edge opens the chats; left closes them.
            if !drawer, g.startLocation.x < 30, g.translation.width > 60 { withAnimation(.easeOut(duration: 0.22)) { drawer = true } }
            if drawer, g.translation.width < -60 { withAnimation(.easeOut(duration: 0.22)) { drawer = false } }
        })
        .preferredColorScheme(.dark)
    }
}

struct NarwhalTopBar: View {
    @EnvironmentObject var narwhal: NarwhalChat
    @Binding var drawer: Bool

    var body: some View {
        HStack(spacing: 6) {
            Button { withAnimation(.easeOut(duration: 0.22)) { drawer = true } } label: {
                Image(systemName: "line.3.horizontal").font(.system(size: 17, weight: .medium))
                    .frame(width: 40, height: 40)
            }
            .accessibilityLabel("Chats")
            Spacer(minLength: 4)
            Text(narwhal.title).font(.system(size: 15, weight: .semibold)).lineLimit(1)
                .foregroundStyle(Ops.text)
            Spacer(minLength: 4)
            Button { narwhal.newChat() } label: {
                Image(systemName: "square.and.pencil").font(.system(size: 17, weight: .medium))
                    .frame(width: 40, height: 40)
            }
            .accessibilityLabel("New chat")
        }
        .foregroundStyle(Ops.dim)
        .padding(.horizontal, 8)
        .frame(height: 46)
    }
}

struct NarwhalDrawer: View {
    @EnvironmentObject var narwhal: NarwhalChat
    @Binding var drawer: Bool
    @Binding var notesOpen: Bool
    @State private var renaming: NarwhalSession?
    @State private var settingsOpen = false
    @State private var newTitle = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                NarwhalMark().frame(width: 44, height: 22)
                Text("narwhal").font(.system(size: 19, weight: .heavy)).fontWidth(.expanded).foregroundStyle(Ops.text)
                Spacer()
            }
            .padding(.horizontal, 18).padding(.top, 14).padding(.bottom, 12)

            Button {
                narwhal.newChat()
                withAnimation(.easeOut(duration: 0.22)) { drawer = false }
            } label: {
                Label("New chat", systemImage: "plus").font(.system(size: 15, weight: .semibold))
                    .frame(maxWidth: .infinity).frame(height: 42)
                    .foregroundStyle(Ops.tusk)
                    .background(Ops.tuskSoft, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .padding(.horizontal, 14).padding(.bottom, 4)

            Button {
                withAnimation(.easeOut(duration: 0.22)) { drawer = false }
                notesOpen = true
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "doc.text").font(.system(size: 15)).foregroundStyle(Ops.dim).frame(width: 20)
                    Text("Notes").font(.system(size: 15)).foregroundStyle(Ops.text)
                    Spacer()
                    if !narwhal.notes.isEmpty {
                        let on = narwhal.notes.filter(\.enabled).count
                        Text(on == narwhal.notes.count ? "\(on)" : "\(on)/\(narwhal.notes.count)")
                            .font(.system(size: 12).monospacedDigit()).foregroundStyle(Ops.faint)
                    }
                }
                .padding(.horizontal, 12).padding(.vertical, 10)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 8).padding(.bottom, 4)

            List {
                ForEach(groups, id: \.0) { group, items in
                    Section {
                        ForEach(items) { s in row(s) }
                    } header: {
                        Text(group).font(.system(size: 12, weight: .medium)).foregroundStyle(Ops.faint)
                            .textCase(nil)
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .refreshable { await narwhal.refresh() }

            Button { settingsOpen = true } label: {
                HStack(spacing: 10) {
                    ProfileAvatar(size: 34)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(narwhal.profileName.isEmpty ? "You" : narwhal.profileName)
                            .font(.custom("Avenir Next", size: 15).weight(.semibold)).foregroundStyle(Ops.text).lineLimit(1)
                        Text("Profile & settings").font(.system(size: 12)).foregroundStyle(Ops.faint)
                    }
                    Spacer()
                    if narwhal.online == false {
                        Circle().fill(Ops.alert).frame(width: 8, height: 8).accessibilityLabel("Can't reach lab3")
                    }
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 16).padding(.vertical, 12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .overlay(alignment: .top) { Rectangle().fill(Ops.line).frame(height: 0.5) }
        }
        .frame(width: 300)
        .frame(maxHeight: .infinity)
        .background(Ops.panel.ignoresSafeArea())
        .sheet(isPresented: $settingsOpen) { NarwhalSettings().environmentObject(narwhal) }
        .alert("Rename chat", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("Title", text: $newTitle)
            Button("Cancel", role: .cancel) {}
            Button("Rename") { if let s = renaming { narwhal.rename(s.id, newTitle) } }
        }
    }

    private func row(_ s: NarwhalSession) -> some View {
        Button {
            narwhal.open(s.id)
            withAnimation(.easeOut(duration: 0.22)) { drawer = false }
        } label: {
            HStack(spacing: 8) {
                Text(s.title).font(.system(size: 15)).lineLimit(1).foregroundStyle(Ops.text)
                Spacer(minLength: 4)
                if s.running { LiveDot() }
            }
            .padding(.horizontal, 10).padding(.vertical, 9)
            .background(s.id == narwhal.current ? Ops.raised : .clear,
                        in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowInsets(EdgeInsets(top: 1, leading: 8, bottom: 1, trailing: 8))
        .listRowBackground(Color.clear)
        .listRowSeparator(.hidden)
        .swipeActions {
            Button(role: .destructive) { narwhal.delete(s.id) } label: { Label("Delete", systemImage: "trash") }
        }
        .contextMenu {
            Button("Rename", systemImage: "pencil") { newTitle = s.title; renaming = s }
            Button("Delete", systemImage: "trash", role: .destructive) { narwhal.delete(s.id) }
        }
    }

    private var groups: [(String, [NarwhalSession])] {
        let cal = Calendar.current
        var out: [(String, [NarwhalSession])] = []
        for s in narwhal.sessions.sorted(by: { $0.date > $1.date }) {
            let days = cal.dateComponents([.day], from: cal.startOfDay(for: s.date), to: cal.startOfDay(for: Date())).day ?? 0
            let g = days < 1 ? "Today" : days < 2 ? "Yesterday" : days < 7 ? "Previous 7 days"
                : days < 30 ? "Previous 30 days" : s.date.formatted(.dateTime.month(.wide).year())
            if out.last?.0 == g { out[out.count - 1].1.append(s) } else { out.append((g, [s])) }
        }
        return out
    }
}

/// The owner's picture: their photo, or initials on their colour.
struct ProfileAvatar: View {
    @EnvironmentObject var narwhal: NarwhalChat
    var size: CGFloat = 32

    var body: some View {
        Group {
            if let p = narwhal.profilePhoto {
                Image(uiImage: p).resizable().scaledToFill()
            } else {
                ZStack {
                    Color(hex: UInt32(narwhal.profileColor.dropFirst(), radix: 16) ?? 0x3ED2D3)
                    Text(initials).font(.system(size: size * 0.38, weight: .bold)).foregroundStyle(Color.black.opacity(0.85))
                }
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
    }

    private var initials: String {
        let words = (narwhal.profileName.isEmpty ? "You" : narwhal.profileName).split(separator: " ")
        return words.prefix(2).compactMap { $0.first.map { String($0).uppercased() } }.joined()
    }
}

/// Narwhal's settings: Claude plan usage, Quick and web search for lab3's
/// models, and Claude's defaults. Same choices as the Mac's Settings panel.
struct NarwhalSettings: View {
    @EnvironmentObject var narwhal: NarwhalChat
    @Environment(\.dismiss) private var dismiss
    @State private var pick: PhotosPickerItem?
    @State private var name = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Profile") {
                    HStack(spacing: 14) {
                        PhotosPicker(selection: $pick, matching: .images) {
                            ProfileAvatar(size: 60)
                                .overlay(alignment: .bottomTrailing) {
                                    Image(systemName: "camera.circle.fill").font(.system(size: 20))
                                        .foregroundStyle(Ops.text, Ops.raised)
                                }
                        }
                        .buttonStyle(.plain)
                        VStack(alignment: .leading, spacing: 10) {
                            TextField("Your name", text: $name)
                                .onSubmit { Task { await narwhal.saveProfile(["name": name]) } }
                            HStack(spacing: 8) {
                                ForEach(NarwhalChat.profileColors, id: \.self) { c in
                                    let hex = String(format: "#%06x", c)
                                    Button { Task { await narwhal.saveProfile(["color": hex]) } } label: {
                                        Circle().fill(Color(hex: c)).frame(width: 20, height: 20)
                                            .overlay(Circle().strokeBorder(Ops.text, lineWidth: narwhal.profileColor == hex ? 2 : 0))
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                    }
                    if narwhal.profilePhoto != nil {
                        Button("Remove photo", role: .destructive) { Task { await narwhal.saveProfile(["avatar": ""]) } }
                    }
                }
                Section {
                    HStack(spacing: 8) {
                        Circle().fill(narwhal.online == true ? Ops.ok : narwhal.online == false ? Ops.alert : Ops.faint)
                            .frame(width: 8, height: 8)
                        Text(narwhal.online == true ? "Synced with lab3" : narwhal.online == false ? "Can't reach lab3" : "Connecting…")
                            .foregroundStyle(Ops.dim)
                    }
                }
                Section("Claude plan usage") {
                    if narwhal.claudeUsage.isEmpty {
                        Text("Shows after Claude's next reply").foregroundStyle(Ops.dim)
                    }
                    ForEach(narwhal.claudeUsage, id: \.name) { w in
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(w.name)
                                Spacer()
                                Text("\(Int((w.used * 100).rounded()))%").bold()
                                Text(Self.resets(w.resets)).foregroundStyle(Ops.faint).font(.system(size: 13))
                            }
                            ProgressView(value: w.used)
                                .tint(w.used >= 0.9 ? .orange : w.used >= 0.7 ? Ops.signal : Ops.tusk)
                        }
                        .padding(.vertical, 2)
                    }
                    if let at = narwhal.claudeUsageAt {
                        Text("As of \(at.formatted(.relative(presentation: .named)))")
                            .font(.system(size: 12)).foregroundStyle(Ops.faint)
                    }
                }
                Section {
                    Toggle(isOn: $narwhal.quick) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Quick answers")
                            Text("Answers straight away instead of thinking first").font(.system(size: 12)).foregroundStyle(Ops.faint)
                        }
                    }
                    Toggle(isOn: $narwhal.web) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Web search")
                            Text("Searches the web (your SearXNG) when it doesn't know").font(.system(size: 12)).foregroundStyle(Ops.faint)
                        }
                    }
                } header: { Text("Narwhal on lab3") }
                Section("Claude") {
                    Picker("Model", selection: $narwhal.claudeModel) {
                        ForEach(NarwhalChat.claudeModels, id: \.0) { m in Text(m.1).tag(m.0) }
                    }
                    Picker("Effort", selection: $narwhal.claudeEffort) {
                        ForEach(NarwhalChat.claudeEfforts, id: \.0) { e in Text(e.1).tag(e.0) }
                    }
                    Picker("Claude may", selection: $narwhal.claudeMode) {
                        ForEach(NarwhalChat.claudeModes, id: \.0) { m in Text(m.1).tag(m.0) }
                    }
                }
            }
            .tint(Ops.tusk)
            .scrollContentBackground(.hidden)
            .background(Ops.ink)
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task { name = narwhal.profileName; await narwhal.loadClaudeUsage(); await narwhal.loadProfile(); name = narwhal.profileName }
            .onChange(of: pick) { _, item in
                Task {
                    if let data = try? await item?.loadTransferable(type: Data.self), let img = UIImage(data: data) {
                        await narwhal.savePhoto(img)
                    }
                }
            }
            .onDisappear { if name != narwhal.profileName { Task { await narwhal.saveProfile(["name": name]) } } }
        }
        .preferredColorScheme(.dark)
    }

    static func resets(_ d: Date?) -> String {
        guard let d, d.timeIntervalSinceNow > 0 else { return "" }
        let s = d.timeIntervalSinceNow
        if s < 3600 { return "· \(max(1, Int(s / 60))) min" }
        if s < 86400 { return "· \(d.formatted(date: .omitted, time: .shortened))" }
        return "· \(d.formatted(.dateTime.weekday(.abbreviated).hour().minute()))"
    }
}

struct LiveDot: View {
    @State private var on = false
    var body: some View {
        Circle().fill(Ops.tusk).frame(width: 7, height: 7)
            .opacity(on ? 0.3 : 1)
            .animation(.easeInOut(duration: 0.7).repeatForever(), value: on)
            .onAppear { on = true }
            .accessibilityLabel("Answering")
    }
}

struct NarwhalEmpty: View {
    @EnvironmentObject var narwhal: NarwhalChat
    @Binding var draft: String
    var focused: FocusState<Bool>.Binding
    @State private var float = false

    var body: some View {
        VStack(spacing: 18) {
            Spacer()
            ZStack {
                // A faint glow, a few bubbles drifting up, and the narwhal
                // swimming gently in place.
                Ellipse()
                    .fill(RadialGradient(colors: [Ops.tusk.opacity(0.12), .clear],
                                         center: .center, startRadius: 0, endRadius: 140))
                    .frame(width: 320, height: 200)
                    .blur(radius: 10)
                    .opacity(float ? 1 : 0.7)
                NarwhalBubbles().frame(width: 260, height: 240)
                NarwhalMark()
                    .frame(width: 196, height: 96)
                    .shadow(color: Ops.tusk.opacity(0.3), radius: 20, y: 6)
                    .rotationEffect(.degrees(float ? -2.5 : 2), anchor: .center)
                    .offset(x: float ? 3 : -3, y: float ? -6 : 6)
            }
            .frame(height: 240)
            .accessibilityHidden(true)
            VStack(spacing: 6) {
                Text(greeting).font(.system(size: 15, weight: .medium)).foregroundStyle(Ops.faint)
                Text("What are we working on?")
                    .font(.system(size: 26, weight: .semibold, design: .rounded))
                    .foregroundStyle(LinearGradient(colors: [Ops.text, Ops.text.opacity(0.78)],
                                                    startPoint: .top, endPoint: .bottom))
                    .multilineTextAlignment(.center)
            }
            .padding(.horizontal, 24)
            Spacer()
            Spacer()
        }
        .frame(maxWidth: .infinity)
        .contentShape(Rectangle())
        .onTapGesture { focused.wrappedValue = false }
        .onAppear {
            withAnimation(.easeInOut(duration: 3.6).repeatForever(autoreverses: true)) { float = true }
        }
    }

    private var greeting: String {
        let h = Calendar.current.component(.hour, from: .now)
        let part = h < 5 ? "Up late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"
        let name = narwhal.profileName.trimmingCharacters(in: .whitespaces)
        return name.isEmpty ? part : "\(part), \(name.split(separator: " ").first.map(String.init) ?? name)"
    }
}

/// Small bubbles rising slowly behind the logo, each wobbling a little and
/// fading out as it nears the top.
struct NarwhalBubbles: View {
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30)) { tl in
            let t = tl.date.timeIntervalSinceReferenceDate
            Canvas { ctx, size in
                for i in 0..<14 {
                    func r(_ k: Double) -> Double { let x = sin(Double(i) * 12.9898 + k * 78.233) * 43758.5453; return x - x.rounded(.down) }
                    let period = 6 + r(1) * 6
                    let p = ((t / period) + r(2)).truncatingRemainder(dividingBy: 1)   // 0 bottom → 1 top
                    let x = size.width * (0.12 + r(3) * 0.76) + sin(t * (0.8 + r(4)) + r(5) * 6) * 6
                    let y = size.height * (1 - p)
                    let d = 2.5 + r(6) * 4.5
                    let fade = min(1, p * 4) * (1 - p)
                    ctx.opacity = 0.55 * fade
                    let rect = CGRect(x: x - d / 2, y: y - d / 2, width: d, height: d)
                    ctx.stroke(Path(ellipseIn: rect), with: .color(Ops.tusk.opacity(0.8)), lineWidth: 0.8)
                    ctx.fill(Path(ellipseIn: rect.insetBy(dx: d * 0.2, dy: d * 0.2).offsetBy(dx: -d * 0.12, dy: -d * 0.12)),
                             with: .color(Ops.tusk.opacity(0.18)))
                }
            }
        }
        .allowsHitTesting(false)
    }
}

/// Graphite, a shade lighter where the logo sits, darker towards the bottom.
struct NarwhalBackdrop: View {
    var body: some View {
        ZStack {
            LinearGradient(colors: [Ops.ink, Color(hex: 0x131418)], startPoint: .top, endPoint: .bottom)
            RadialGradient(colors: [Ops.tusk.opacity(0.05), .clear], center: .init(x: 0.5, y: 0.38),
                           startRadius: 0, endRadius: 420)
        }
    }
}

struct NarwhalLog: View {
    @EnvironmentObject var narwhal: NarwhalChat

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                // A plain VStack: a lazy one guesses the height of rows it
                // hasn't drawn, so scrolling to the end overshot into blank.
                VStack(alignment: .leading, spacing: 18) {
                    ForEach(narwhal.turns) { t in
                        if t.role == "user" { UserBubble(turn: t) }
                        else { AnswerBlock(turn: t, live: t.id == narwhal.liveID) }
                    }
                    Color.clear.frame(height: 1).id("end")
                }
                .padding(.horizontal, 16).padding(.vertical, 12)
            }
            .defaultScrollAnchor(.bottom)
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: narwhal.turns) { _, _ in proxy.scrollTo("end", anchor: .bottom) }
            .onAppear { proxy.scrollTo("end", anchor: .bottom) }
        }
    }
}

struct UserBubble: View {
    let turn: NarwhalTurn
    var body: some View {
        HStack {
            Spacer(minLength: 48)
            Text(turn.text).font(.system(size: 15.5)).foregroundStyle(Ops.text).textSelection(.enabled)
                .padding(.horizontal, 15).padding(.vertical, 10)
                .background(Ops.raised, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                .opacity(turn.pending ? 0.6 : 1)
        }
    }
}

struct AnswerBlock: View {
    @EnvironmentObject var narwhal: NarwhalChat
    let turn: NarwhalTurn
    let live: Bool
    @State private var showThinking: Bool?
    @State private var copied = false

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            NarwhalMark(colour: Ops.routeColour(turn.route)).frame(width: 26, height: 14)
                .frame(width: 30, height: 30)
                .overlay(Circle().strokeBorder(Ops.line, lineWidth: 1))
            VStack(alignment: .leading, spacing: 10) {
                if !turn.thinking.isEmpty {
                    let open = showThinking ?? (live && turn.text.isEmpty)
                    Button { withAnimation(.easeOut(duration: 0.2)) { showThinking = !open } } label: {
                        HStack(spacing: 6) {
                            Text(thoughtLabel)
                            Image(systemName: "chevron.down").font(.system(size: 10, weight: .semibold))
                                .rotationEffect(.degrees(open ? 180 : 0))
                        }
                        .font(.system(size: 13)).foregroundStyle(Ops.dim)
                        .padding(.horizontal, 11).padding(.vertical, 6)
                        .background(Ops.panel, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                    if open {
                        Text(turn.thinking.trimmingCharacters(in: .whitespacesAndNewlines))
                            .font(.system(size: 13.5)).foregroundStyle(Ops.dim).textSelection(.enabled)
                            .padding(.leading, 12)
                            .overlay(alignment: .leading) { Rectangle().fill(Ops.line).frame(width: 2) }
                    }
                } else if live && turn.text.isEmpty {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small).tint(Ops.tusk)
                        Text(turn.label.map { "Waking \($0)…" } ?? "Working…")
                    }
                    .font(.system(size: 13.5)).foregroundStyle(Ops.dim)
                }

                if !turn.text.isEmpty { RichAnswer(text: turn.text) }

                if turn.status == "error" {
                    Text(turn.error ?? "Something went wrong.").font(.system(size: 14)).foregroundStyle(Ops.alert)
                } else if turn.status == "stopped" && !live {
                    Text("Stopped").font(.system(size: 13)).foregroundStyle(Ops.faint)
                }
                meta
            }
        }
    }

    private var thoughtLabel: String {
        if live && turn.text.isEmpty { return "Thinking…" }
        guard let s = turn.thinkSeconds else { return "Thought for a moment" }
        let n = max(1, Int(s.rounded()))
        return n == 1 ? "Thought for 1 second" : "Thought for \(n) seconds"
    }

    @ViewBuilder private var meta: some View {
        HStack(spacing: 4) {
            if !live {
                Button {
                    UIPasteboard.general.string = turn.text
                    copied = true
                    Task { try? await Task.sleep(for: .seconds(1.5)); copied = false }
                } label: {
                    Image(systemName: copied ? "checkmark" : "doc.on.doc").frame(width: 30, height: 28)
                }
                .accessibilityLabel("Copy")
                Button { narwhal.retry(turn) } label: {
                    Image(systemName: "arrow.clockwise").frame(width: 30, height: 28)
                }
                .accessibilityLabel("Ask again")
            }
            if let label = turn.label ?? turn.model {
                HStack(spacing: 4) {
                    Image(systemName: turn.route == "code" ? "chevron.left.forwardslash.chevron.right" : turn.route == "claude" ? "sparkle" : "shield")
                        .font(.system(size: 9, weight: .semibold))
                    Text(label).lineLimit(1)
                }
                .fixedSize()
                .font(.system(size: 11.5, weight: .semibold))
                .foregroundStyle(Ops.routeColour(turn.route))
                .padding(.horizontal, 8).padding(.vertical, 3)
                .background(Ops.routeSoft(turn.route), in: Capsule())
            }
            if !live, !stats.isEmpty {
                Text(stats).font(.system(size: 11.5)).foregroundStyle(Ops.faint).lineLimit(1).padding(.leading, 4)
            }
        }
        .font(.system(size: 13))
        .foregroundStyle(Ops.faint)
    }

    private var stats: String {
        var bits: [String] = []
        if let r = turn.tokS { bits.append(String(format: "%.1f tok/s", r)) }
        if let n = turn.completionTokens { bits.append("\(compact(n)) tokens") }
        if let s = turn.seconds { bits.append(String(format: "%.1fs", s)) }
        return bits.joined(separator: " · ")
    }
}

func compact(_ n: Int) -> String {
    n >= 10_000 ? "\(n / 1000)k" : n >= 1000 ? String(format: "%.1fk", Double(n) / 1000) : "\(n)"
}

/// Markdown text with ``` code fences drawn as code panels (copyable).
struct RichAnswer: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(segments.enumerated()), id: \.offset) { _, seg in
                if seg.code {
                    CodePanel(lang: seg.lang, code: seg.body)
                } else {
                    ForEach(Array(blocks(seg.body).enumerated()), id: \.offset) { _, b in block(b) }
                }
            }
        }
    }

    private struct Segment { var code: Bool; var lang: String; var body: String }

    private var segments: [Segment] {
        var out: [Segment] = []
        let parts = text.components(separatedBy: "```")
        for (i, part) in parts.enumerated() {
            if i % 2 == 0 {
                out.append(Segment(code: false, lang: "", body: part))
            } else {
                var lines = part.components(separatedBy: "\n")
                let lang = lines.first?.trimmingCharacters(in: .whitespaces) ?? ""
                if !lines.isEmpty { lines.removeFirst() }
                out.append(Segment(code: true, lang: lang, body: lines.joined(separator: "\n").trimmingCharacters(in: .newlines)))
            }
        }
        return out
    }

    // Block-level markdown, line by line: headings, lists, tables, rules.
    private enum Block {
        case heading(Int, String), bullet(String), numbered(String, String)
        case table([[String]]), rule, paragraph(String)
    }

    private func blocks(_ body: String) -> [Block] {
        var out: [Block] = []
        var para: [String] = []
        var table: [[String]] = []
        func flushPara() { if !para.isEmpty { out.append(.paragraph(para.joined(separator: "\n"))); para = [] } }
        func flushTable() { if !table.isEmpty { out.append(.table(table)); table = [] } }
        for raw in body.components(separatedBy: "\n") {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("|") {
                flushPara()
                let cells = line.trimmingCharacters(in: CharacterSet(charactersIn: "|"))
                    .components(separatedBy: "|").map { $0.trimmingCharacters(in: .whitespaces) }
                if !cells.allSatisfy({ $0.allSatisfy { "-: ".contains($0) } }) { table.append(cells) }
                continue
            }
            flushTable()
            if line.isEmpty { flushPara(); continue }
            if let m = line.firstMatch(of: /^(#{1,6})\s+(.*)$/) {
                flushPara(); out.append(.heading(m.1.count, String(m.2)))
            } else if line.wholeMatch(of: /^(-{3,}|\*{3,}|_{3,})$/) != nil {
                flushPara(); out.append(.rule)
            } else if let m = line.firstMatch(of: /^[-*•+]\s+(.*)$/) {
                flushPara(); out.append(.bullet(String(m.1)))
            } else if let m = line.firstMatch(of: /^(\d+)[.)]\s+(.*)$/) {
                flushPara(); out.append(.numbered(String(m.1), String(m.2)))
            } else {
                para.append(line)
            }
        }
        flushPara(); flushTable()
        return out
    }

    @ViewBuilder private func block(_ b: Block) -> some View {
        switch b {
        case .heading(let level, let t):
            Text(markdown(t))
                .font(.system(size: level <= 1 ? 19 : level == 2 ? 17 : 15.5, weight: .semibold))
                .foregroundStyle(Ops.text)
                .padding(.top, 4)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .bullet(let t):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("•").foregroundStyle(Ops.dim)
                body(t)
            }
        case .numbered(let n, let t):
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text("\(n).").foregroundStyle(Ops.dim).frame(minWidth: 18, alignment: .trailing)
                body(t)
            }
            .font(.system(size: 15.5))
        case .rule:
            Rectangle().fill(Ops.line).frame(height: 0.5).padding(.vertical, 4)
        case .table(let rows):
            // Too narrow for columns: each row is a small card, its first
            // cell as the title and the rest under their column names.
            let head = rows.first ?? []
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(rows.dropFirst().enumerated()), id: \.offset) { i, row in
                    VStack(alignment: .leading, spacing: 4) {
                        if let first = row.first {
                            Text(markdown(first)).font(.system(size: 14.5, weight: .semibold)).foregroundStyle(Ops.text)
                        }
                        ForEach(Array(row.dropFirst().enumerated()), id: \.offset) { j, cell in
                            HStack(alignment: .firstTextBaseline, spacing: 6) {
                                if j + 1 < head.count, !head[j + 1].isEmpty {
                                    Text(head[j + 1]).font(.system(size: 12.5)).foregroundStyle(Ops.faint)
                                }
                                Text(markdown(cell)).font(.system(size: 14)).foregroundStyle(Ops.text)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 12).padding(.vertical, 9)
                    .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Ops.line).frame(height: 0.5) } }
                }
            }
            .background(Ops.panel, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Ops.line, lineWidth: 1))
        case .paragraph(let t):
            body(t).frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func body(_ t: String) -> some View {
        Text(markdown(t)).font(.system(size: 15.5)).foregroundStyle(Ops.text).lineSpacing(3)
            .tint(Ops.tusk).textSelection(.enabled)
    }

    private func markdown(_ s: String) -> AttributedString {
        var out = (try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
            ?? AttributedString(s)
        for run in out.runs where run.inlinePresentationIntent?.contains(.code) == true {
            out[run.range].font = Ops.mono(13.5)
            out[run.range].backgroundColor = Ops.code
        }
        return out
    }
}

struct CodePanel: View {
    let lang: String, code: String
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(lang.isEmpty ? "code" : lang).font(Ops.mono(12))
                Spacer()
                Button {
                    UIPasteboard.general.string = code
                    copied = true
                    Task { try? await Task.sleep(for: .seconds(1.5)); copied = false }
                } label: {
                    Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc")
                        .font(.system(size: 12))
                }
            }
            .foregroundStyle(Ops.dim)
            .padding(.horizontal, 12).padding(.vertical, 7)
            .background(Ops.raised)
            ScrollView(.horizontal, showsIndicators: false) {
                Text(code).font(Ops.mono(12.5)).foregroundStyle(Ops.text)
                    .textSelection(.enabled).fixedSize().padding(12)
            }
        }
        .background(Ops.code)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Ops.line, lineWidth: 1))
    }
}

struct NarwhalComposer: View {
    @EnvironmentObject var narwhal: NarwhalChat
    @Binding var draft: String
    var focused: FocusState<Bool>.Binding

    private var empty: Bool { draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("", text: $draft, prompt: Text("Message Narwhal").foregroundStyle(Ops.faint), axis: .vertical)
                .lineLimit(1...7)
                .font(.system(size: 16))
                .foregroundStyle(Ops.text)
                .tint(Ops.tusk)
                .focused(focused)
            HStack(spacing: 6) {
                chip("auto", "Auto", "arrow.triangle.branch")
                chip("security", "Security", "shield")
                chip("code", "Code", "chevron.left.forwardslash.chevron.right")
                chip("claude", "Claude", "sparkle")   // Claude Code on lab3, picked by hand
                Spacer(minLength: 4)
                TimelineView(.periodic(from: .now, by: 0.5)) { _ in
                    HStack(spacing: 8) {
                        if let s = narwhal.speed {
                            Text(s).foregroundStyle(narwhal.liveID != nil ? Ops.tusk : Ops.faint).lineLimit(1).fixedSize()
                        }
                        if narwhal.current != nil { ContextRing() }
                    }
                    .font(.system(size: 11.5).monospacedDigit())
                    .foregroundStyle(Ops.faint)
                }
                Button {
                    if narwhal.running { narwhal.stop() } else { narwhal.send(draft); draft = "" }
                } label: {
                    Image(systemName: narwhal.running ? "stop.fill" : "arrow.up")
                        .font(.system(size: narwhal.running ? 12 : 15, weight: .bold))
                        .frame(width: 34, height: 34)
                        .foregroundStyle(narwhal.running ? Ops.ink : (empty ? Ops.faint : Ops.ink))
                        .background(narwhal.running ? Ops.text : (empty ? Ops.line : Ops.tusk), in: Circle())
                        .shadow(color: Ops.tusk.opacity(!narwhal.running && !empty ? 0.5 : 0), radius: 8)
                        .animation(.easeOut(duration: 0.15), value: empty)
                }
                .disabled(!narwhal.running && empty)
                .accessibilityLabel(narwhal.running ? "Stop" : "Send")
            }
        }
        .padding(.horizontal, 16).padding(.top, 13).padding(.bottom, 10)
        .background(LinearGradient(colors: [Color(hex: 0x23262D), Ops.panel], startPoint: .top, endPoint: .bottom),
                    in: RoundedRectangle(cornerRadius: 26, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 26, style: .continuous)
            .strokeBorder(focused.wrappedValue ? Ops.tusk.opacity(0.45) : Color.white.opacity(0.07), lineWidth: 1))
        .shadow(color: .black.opacity(0.35), radius: 18, y: 6)
        .padding(.horizontal, 12).padding(.bottom, 8).padding(.top, 4)
        .animation(.easeOut(duration: 0.15), value: focused.wrappedValue)
    }

    private func chip(_ route: String, _ title: String, _ icon: String) -> some View {
        let on = narwhal.route == route
        let colour = route == "code" ? Ops.coder : Ops.tusk
        return Button { withAnimation(.easeOut(duration: 0.15)) { narwhal.route = route } } label: {
            HStack(spacing: 4) {
                Image(systemName: icon).font(.system(size: 11, weight: .semibold))
                if on { Text(title).fixedSize() }
            }
            .font(.system(size: 12.5, weight: .medium))
            .foregroundStyle(on ? colour : Ops.dim)
            .padding(.horizontal, on ? 10 : 0).frame(minWidth: 30).frame(height: 30)
            .background(on ? (route == "code" ? Ops.coderSoft : Ops.tuskSoft) : .clear, in: Capsule())
            .overlay(Capsule().strokeBorder(on ? .clear : Ops.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .layoutPriority(on ? 1 : 0)
        .accessibilityLabel(title)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// How much of the model's context window the chat uses now.
struct ContextRing: View {
    @EnvironmentObject var narwhal: NarwhalChat
    var body: some View {
        let c = narwhal.contextUsed
        let pct = min(1, Double(c.used) / Double(max(1, c.window)))
        let colour = pct >= 0.9 ? Ops.alert : pct >= 0.7 ? Ops.signal : Ops.tusk
        HStack(spacing: 5) {
            ZStack {
                Circle().stroke(Ops.line, lineWidth: 2.5)
                Circle().trim(from: 0, to: pct).stroke(colour, style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                    .rotationEffect(.degrees(-90))
            }
            .frame(width: 14, height: 14)
            Text(compact(c.used)).lineLimit(1).fixedSize()
        }
        .accessibilityLabel("\(Int(pct * 100)) percent of the context window used, \(compact(c.used)) of \(compact(c.window)) tokens")
    }
}

// MARK: switching between them

/// Marina and Narwhal side by side: swipe between them, or use the toggle.
struct RootView: View {
    @AppStorage("section") private var page = 0

    var body: some View {
        TabView(selection: $page) {
            ContentView().tag(0)
            NarwhalView().tag(1)
        }
        .tabViewStyle(.page(indexDisplayMode: .never))
        .ignoresSafeArea(.container, edges: .bottom)
        .safeAreaInset(edge: .top, spacing: 0) { SectionToggle(page: $page) }
        .background(page == 0 ? Color.night : Ops.ink)
        .animation(.easeInOut(duration: 0.3), value: page)
    }
}

struct SectionToggle: View {
    @Binding var page: Int
    @Namespace private var ns

    var body: some View {
        let ops = page == 1
        HStack(spacing: 2) {
            item("Marina", 0, colour: Color.accent)
            item("Narwhal", 1, colour: Ops.tusk)
        }
        .padding(3)
        .background(ops ? AnyShapeStyle(Ops.panel) : AnyShapeStyle(.ultraThinMaterial),
                    in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
            .strokeBorder(ops ? Ops.line : .white.opacity(0.1), lineWidth: 0.5))
        .frame(maxWidth: .infinity)
        .padding(.top, 2).padding(.bottom, 4)
        .background(alignment: .top) {
            (ops ? Ops.ink : Color(red: 0.13, green: 0.11, blue: 0.24)).ignoresSafeArea(edges: .top)
        }
    }

    private func item(_ title: String, _ tag: Int, colour: Color) -> some View {
        let on = page == tag
        return Button {
            withAnimation(.spring(duration: 0.35)) { page = tag }
        } label: {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(on ? Color.black : .white.opacity(0.7))
                .padding(.horizontal, 14).padding(.vertical, 6)
                .background {
                    if on {
                        RoundedRectangle(cornerRadius: 15, style: .continuous)
                            .fill(colour)
                            .matchedGeometryEffect(id: "pill", in: ns)
                    }
                }
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}


// MARK: notes

/// The owner's notes for Narwhal: a list with the budget on top, each
/// opening an editor that saves as you type. Shared with the Mac.
struct NarwhalNotesView: View {
    @EnvironmentObject var narwhal: NarwhalChat
    @Environment(\.dismiss) private var dismiss
    @State private var path: [String] = []

    var body: some View {
        NavigationStack(path: $path) {
            Group {
                if narwhal.notes.isEmpty { empty } else { list }
            }
            .background(Ops.ink.ignoresSafeArea())
            .navigationTitle("Notes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Done") { dismiss() }.foregroundStyle(Ops.tusk)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { add() } label: { Image(systemName: "plus") }
                        .foregroundStyle(Ops.tusk)
                        .accessibilityLabel("New note")
                }
            }
            .navigationDestination(for: String.self) { id in
                NarwhalNoteEditor(id: id).environmentObject(narwhal)
            }
            .toolbarBackground(Ops.ink, for: .navigationBar)
        }
        .preferredColorScheme(.dark)
        .task { await narwhal.loadNotes() }
    }

    private func add() {
        Task { if let n = await narwhal.addNote() { path.append(n.id) } }
    }

    private var list: some View {
        List {
            Section {
                ForEach(narwhal.notes) { n in
                    NavigationLink(value: n.id) { NoteRow(note: n) }
                        .listRowBackground(Ops.panel)
                }
                .onDelete { idx in idx.map { narwhal.notes[$0].id }.forEach(narwhal.deleteNote) }
            } header: {
                NotesBudget(used: narwhal.notesUsed, max: narwhal.notesMax)
                    .textCase(nil).padding(.bottom, 6)
            } footer: {
                Text("Every note that's on goes with each message, to both models. Swipe to delete.")
                    .font(.system(size: 12)).foregroundStyle(Ops.faint)
            }
        }
        .scrollContentBackground(.hidden)
        .refreshable { await narwhal.loadNotes() }
    }

    private var empty: some View {
        ScrollView {
            VStack(spacing: 14) {
                NarwhalMark().frame(width: 140, height: 68)
                    .shadow(color: Ops.tusk.opacity(0.3), radius: 18, y: 6)
                    .padding(.top, 50).padding(.bottom, 6)
                Text("Give Narwhal a memory").font(.system(size: 20, weight: .semibold)).foregroundStyle(Ops.text)
                Text("Notes go with every message, to both models. Write down what you'd otherwise explain again: your projects, how they're laid out, which box is where.")
                    .font(.system(size: 14)).foregroundStyle(Ops.dim).multilineTextAlignment(.center)
                    .padding(.horizontal, 30)
                Text("lab3  192.168.1.15   Proxmox\nlab2  192.168.1.131  Mint desktop\n~/narwhal  app/ songbird/ code/")
                    .font(Ops.mono(12)).foregroundStyle(Ops.dim)
                    .padding(.horizontal, 16).padding(.vertical, 12)
                    .background(Ops.code, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Ops.line))
                    .padding(.top, 6)
                Button { add() } label: {
                    Label("New note", systemImage: "plus").font(.system(size: 15, weight: .semibold))
                        .padding(.horizontal, 18).frame(height: 42)
                        .foregroundStyle(Ops.ink)
                        .background(Ops.tusk, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                .padding(.top, 8)
            }
            .frame(maxWidth: .infinity)
        }
    }
}

struct NoteRow: View {
    let note: NarwhalNote
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Circle()
                .fill(note.enabled ? Ops.tusk : .clear)
                .overlay(Circle().strokeBorder(note.enabled ? .clear : Ops.faint, lineWidth: 1.5))
                .frame(width: 8, height: 8).padding(.top, 6)
            VStack(alignment: .leading, spacing: 2) {
                Text(note.title).font(.system(size: 15)).foregroundStyle(Ops.text).lineLimit(1)
                Text(note.preview).font(Ops.mono(12)).foregroundStyle(Ops.faint).lineLimit(1)
                if note.enabled && !note.included && !note.body.isEmpty {
                    Text("Over the budget, not sent").font(.system(size: 11)).foregroundStyle(Ops.alert)
                }
            }
            .opacity(note.enabled ? 1 : 0.5)
        }
        .padding(.vertical, 3)
    }
}

struct NotesBudget: View {
    let used: Int, max: Int
    var body: some View {
        let pct = min(1, Double(used) / Double(Swift.max(max, 1)))
        VStack(alignment: .leading, spacing: 6) {
            Text("\(used.formatted()) / \(max.formatted()) characters sent with every message")
                .font(.system(size: 12).monospacedDigit()).foregroundStyle(Ops.faint)
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(Ops.line)
                    Capsule().fill(pct >= 0.9 ? Ops.alert : pct >= 0.7 ? Ops.signal : Ops.tusk)
                        .frame(width: g.size.width * pct)
                }
            }
            .frame(height: 4)
        }
    }
}

struct NarwhalNoteEditor: View {
    @EnvironmentObject var narwhal: NarwhalChat
    @Environment(\.dismiss) private var dismiss
    let id: String
    @State private var title = ""
    @State private var text = ""
    @State private var loaded = false
    @State private var status = ""
    @State private var saveTask: Task<Void, Never>?
    @State private var dirty = false
    @State private var confirmDelete = false
    @State private var bodyFocused = false
    @FocusState private var titleFocused: Bool

    private var note: NarwhalNote? { narwhal.notes.first { $0.id == id } }

    var body: some View {
        VStack(spacing: 0) {
            TextField("Title", text: $title)
                .font(.system(size: 22, weight: .semibold)).foregroundStyle(Ops.text)
                .focused($titleFocused)
                .submitLabel(.next).onSubmit { bodyFocused = true }
                .padding(.horizontal, 18).padding(.top, 10).padding(.bottom, 6)
            Toggle(isOn: Binding(get: { note?.enabled ?? true },
                                 set: { on in Task { await save(); await narwhal.saveNote(id, enabled: on) } })) {
                Text("Narwhal reads this").font(.system(size: 14)).foregroundStyle(Ops.dim)
            }
            .tint(Ops.tusk)
            .padding(.horizontal, 18).padding(.bottom, 8)
            Rectangle().fill(Ops.line).frame(height: 0.5)
            PlainTextView(text: $text, focused: $bodyFocused)
                .padding(.horizontal, 13).padding(.top, 4)
                .overlay(alignment: .topLeading) {
                    if text.isEmpty {
                        Text("What the project is, how it's laid out, addresses, ports, which box runs what.")
                            .font(Ops.mono(14)).foregroundStyle(Ops.faint)
                            .padding(.horizontal, 18).padding(.top, 12).allowsHitTesting(false)
                    }
                }
            HStack {
                Text("\(text.count.formatted()) / \(NarwhalChat.noteMax.formatted())")
                    .foregroundStyle(text.count > NarwhalChat.noteMax ? Ops.alert : Ops.faint)
                Text(status).foregroundStyle(Ops.faint)
                Spacer()
            }
            .font(.system(size: 12).monospacedDigit())
            .padding(.horizontal, 18).padding(.vertical, 10)
            .overlay(alignment: .top) { Rectangle().fill(Ops.line).frame(height: 0.5) }
        }
        .background(Ops.ink.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button(role: .destructive) { confirmDelete = true } label: { Image(systemName: "trash") }
                    .foregroundStyle(Ops.alert)
                    .accessibilityLabel("Delete note")
            }
        }
        .confirmationDialog("Delete this note? Narwhal will forget it.", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) {
                saveTask?.cancel(); dirty = false
                narwhal.deleteNote(id); dismiss()
            }
        }
        .onAppear {
            guard !loaded, let n = note else { return }
            title = n.title == "Untitled" && n.body.isEmpty ? "" : n.title
            text = n.body
            loaded = true
            if n.body.isEmpty { if title.isEmpty { titleFocused = true } else { bodyFocused = true } }
        }
        .onChange(of: title) { _, _ in queue() }
        .onChange(of: text) { _, _ in queue() }
        .onDisappear { Task { await save() } }
    }

    private func queue() {
        guard loaded, let n = note else { return }
        // Filling the fields on open isn't an edit.
        if !dirty && text == n.body && (title == n.title || (title.isEmpty && n.title == "Untitled")) { return }
        dirty = true; status = "· editing"
        saveTask?.cancel()
        saveTask = Task {
            try? await Task.sleep(for: .milliseconds(700))
            if !Task.isCancelled { await save() }
        }
    }

    private func save() async {
        guard dirty, note != nil else { return }
        guard text.count <= NarwhalChat.noteMax else { status = "· too long to save"; return }
        dirty = false; status = "· saving"
        if await narwhal.saveNote(id, title: title, body: text) {
            if !dirty { status = "· saved" }
        } else {
            dirty = true; status = "· not saved"
        }
    }
}

/// A text view for notes full of commands, paths and addresses: monospaced,
/// with no smart quotes, dashes or autocorrect to mangle them.
struct PlainTextView: UIViewRepresentable {
    @Binding var text: String
    @Binding var focused: Bool

    func makeUIView(context: Context) -> UITextView {
        let v = UITextView()
        v.backgroundColor = .clear
        v.font = .monospacedSystemFont(ofSize: 14, weight: .regular)
        v.textColor = UIColor(Ops.text)
        v.tintColor = UIColor(Ops.tusk)
        v.autocorrectionType = .no
        v.autocapitalizationType = .none
        v.spellCheckingType = .no
        v.smartQuotesType = .no
        v.smartDashesType = .no
        v.smartInsertDeleteType = .no
        v.keyboardDismissMode = .interactive
        v.alwaysBounceVertical = true
        v.textContainerInset = UIEdgeInsets(top: 8, left: 0, bottom: 16, right: 0)
        v.delegate = context.coordinator
        return v
    }

    func updateUIView(_ v: UITextView, context: Context) {
        if v.text != text { v.text = text }
        if focused && !v.isFirstResponder { DispatchQueue.main.async { v.becomeFirstResponder() } }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, UITextViewDelegate {
        let parent: PlainTextView
        init(_ p: PlainTextView) { parent = p }
        func textViewDidChange(_ v: UITextView) { parent.text = v.text }
        func textViewDidBeginEditing(_ v: UITextView) { parent.focused = true }
        func textViewDidEndEditing(_ v: UITextView) { parent.focused = false }
    }
}
