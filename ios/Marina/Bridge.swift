import Foundation

/// One line of the bridge's NDJSON stream, kept as plain JSON so chunks can be
/// handed to the avatar page exactly as the Mac app receives them.
struct BridgeEvent {
    let raw: [String: Any]

    var type: String { raw["type"] as? String ?? "" }
    func string(_ key: String) -> String? { raw[key] as? String }
    func int(_ key: String) -> Int? { (raw[key] as? NSNumber)?.intValue }
}

enum BridgeError: LocalizedError {
    case notConfigured
    case status(Int)
    case forbidden

    var errorDescription: String? {
        switch self {
        case .notConfigured: return "Add the bridge address and token in Settings."
        case .forbidden: return "The bridge refused the token. Check it in Settings."
        case .status(let code): return "The bridge answered \(code)."
        }
    }
}

struct NarwhalError: LocalizedError {
    let status: Int
    let message: String
    var errorDescription: String? { message }
}

struct HistoryMessage: Decodable {
    let role: String
    let content: String
    let at: String?
}

/// Talks to Marina's bridge on lab3: the same endpoints the Mac app and the
/// phone page use, with the bridge's web token as a bearer token.
final class Bridge {
    var baseURL: URL?
    var token: String

    private let session: URLSession = {
        let c = URLSessionConfiguration.default
        c.timeoutIntervalForRequest = 180     // a long reply can pause between sentences
        c.timeoutIntervalForResource = 600
        c.waitsForConnectivity = false
        return URLSession(configuration: c)
    }()

    init(baseURL: URL?, token: String) {
        self.baseURL = baseURL
        self.token = token
    }

    private func request(_ path: String, method: String = "GET", query: [URLQueryItem] = []) throws -> URLRequest {
        guard let baseURL, !token.isEmpty else { throw BridgeError.notConfigured }
        var comps = URLComponents(url: baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { comps.queryItems = query }
        var req = URLRequest(url: comps.url!)
        req.httpMethod = method
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return req
    }

    private func check(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else { return }
        if http.statusCode == 403 { throw BridgeError.forbidden }
        guard (200..<300).contains(http.statusCode) else { throw BridgeError.status(http.statusCode) }
    }

    // MARK: plain calls

    func health() async throws -> [String: Any] {
        var req = try request("health")
        req.timeoutInterval = 6
        let (data, response) = try await session.data(for: req)
        try check(response)
        return (try JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
    }

    func history() async throws -> [HistoryMessage] {
        let (data, response) = try await session.data(for: try request("shared/history"))
        try check(response)
        return (try? JSONDecoder().decode([HistoryMessage].self, from: data)) ?? []
    }

    /// A screenshot of the machine she works on (lab2), small unless full.
    func screen(full: Bool = false) async throws -> Data {
        var req = try request("workspace/screen", query: full ? [URLQueryItem(name: "full", value: "true")] : [])
        req.timeoutInterval = 25
        let (data, response) = try await session.data(for: req)
        try check(response)
        return data
    }

    /// Her personalities, and which one is on. POST a name to switch.
    func presets() async throws -> (current: String, all: [(name: String, label: String)]) {
        var req = try request("preset")
        req.timeoutInterval = 8
        let (data, response) = try await session.data(for: req)
        try check(response)
        let o = (try JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        let all = (o["presets"] as? [[String: Any]] ?? []).compactMap { p -> (String, String)? in
            guard let n = p["name"] as? String else { return nil }
            return (n, p["label"] as? String ?? n)
        }
        return (o["preset"] as? String ?? "default", all.map { (name: $0.0, label: $0.1) })
    }

    /// Little sounds ("mm-hm") in her current voice, as base64 WAVs.
    func backchannel() async throws -> [String] {
        var req = try request("backchannel")
        req.timeoutInterval = 60
        let (data, response) = try await session.data(for: req)
        try check(response)
        let o = (try JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        return o["clips"] as? [String] ?? []
    }

    func post(_ path: String, json: [String: Any] = [:]) async throws {
        var req = try request(path, method: "POST")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: json)
        let (_, response) = try await session.data(for: req)
        try check(response)
    }

    // MARK: streams

    /// Her reply to a typed message, one sentence per chunk.
    func chat(_ text: String, speak: Bool) throws -> AsyncThrowingStream<BridgeEvent, Error> {
        var req = try request("chat/stream", method: "POST")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["text": text, "speak": speak])
        return stream(req)
    }

    /// A voice note: the bridge transcribes it, then streams her reply.
    func voice(_ file: URL) throws -> AsyncThrowingStream<BridgeEvent, Error> {
        var req = try request("voice/stream", method: "POST")
        let boundary = "marina-\(UUID().uuidString)"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"audio\"; filename=\"\(file.lastPathComponent)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/mp4\r\n\r\n".data(using: .utf8)!)
        body.append((try? Data(contentsOf: file)) ?? Data())
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        req.httpBody = body
        return stream(req)
    }

    /// Hands-free: one phrase as a 16-bit WAV. The bridge answers only if it
    /// was said to her (or `follow` is set), else sends {"type": "ignored"}.
    /// `follow`: just after she answered. `any`: the "no need to say her
    /// name" setting, which a personality like Berri can overrule.
    func hear(_ wav: Data, follow: Bool, any: Bool = false) throws -> AsyncThrowingStream<BridgeEvent, Error> {
        var query: [URLQueryItem] = []
        if follow { query.append(URLQueryItem(name: "follow", value: "true")) }
        if any { query.append(URLQueryItem(name: "any", value: "true")) }
        var req = try request("hear", method: "POST", query: query)
        let boundary = "marina-\(UUID().uuidString)"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"audio\"; filename=\"phrase.wav\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        body.append(wav)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        req.httpBody = body
        return stream(req)
    }

    /// Narwhal: the whole conversation each time (the bridge keeps none of
    /// it); streams start / think / text / done / error.
    func narwhal(_ messages: [[String: String]]) throws -> AsyncThrowingStream<BridgeEvent, Error> {
        var req = try request("narwhal/stream", method: "POST")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["messages": messages])
        req.timeoutInterval = 300      // the model may need loading in first
        return stream(req)
    }

    /// Narwhal's synced sessions (kept on lab3, shared with the Mac): a plain
    /// JSON call. Errors carry the bridge's own message when it sends one.
    func narwhalCall(_ path: String, method: String = "GET", body: [String: Any]? = nil) async throws -> Any {
        var req = try request(path, method: method)
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        req.timeoutInterval = 30
        let (data, response) = try await session.data(for: req)
        if let http = response as? HTTPURLResponse, http.statusCode >= 400 {
            if http.statusCode == 403 { throw BridgeError.forbidden }
            let msg = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
            throw NarwhalError(status: http.statusCode, message: msg ?? "The bridge answered \(http.statusCode).")
        }
        return try JSONSerialization.jsonObject(with: data)
    }

    /// A long-lived NDJSON stream from the bridge: a session's events
    /// (`narwhal/sessions/{id}/follow`) or every session's changes
    /// (`narwhal/watch`). The bridge pings every 15 s, so a quiet minute
    /// means the line is dead.
    func narwhalStream(_ path: String, query: [URLQueryItem] = []) throws -> AsyncThrowingStream<BridgeEvent, Error> {
        var req = try request(path, query: query)
        req.timeoutInterval = 60
        return stream(req)
    }

    /// Long poll for something she says unprompted: a timer going off, a
    /// follow-up, or just checking in.
    func idle(timeout: Int = 120) throws -> AsyncThrowingStream<BridgeEvent, Error> {
        // client=phone: the bridge only speaks into this poll while the app
        // says it's in front, and pushes through ntfy otherwise.
        var req = try request("idle/listen", query: [URLQueryItem(name: "timeout", value: String(timeout)),
                                                     URLQueryItem(name: "client", value: "phone")])
        req.timeoutInterval = TimeInterval(timeout + 30)
        return stream(req)
    }

    private func stream(_ req: URLRequest) -> AsyncThrowingStream<BridgeEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await session.bytes(for: req)
                    try check(response)
                    for try await line in bytes.lines {
                        let trimmed = line.trimmingCharacters(in: .whitespaces)
                        guard !trimmed.isEmpty,
                              let data = trimmed.data(using: .utf8),
                              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                        else { continue }
                        continuation.yield(BridgeEvent(raw: obj))
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
