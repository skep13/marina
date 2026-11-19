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

    /// Long poll for something she says unprompted: a timer going off, a
    /// follow-up, or just checking in.
    func idle(timeout: Int = 120) throws -> AsyncThrowingStream<BridgeEvent, Error> {
        var req = try request("idle/listen", query: [URLQueryItem(name: "timeout", value: String(timeout))])
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
