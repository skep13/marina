import SwiftUI
import WebKit
import UniformTypeIdentifiers

/// Draws Marina with the same renderer and VRM as the Mac app. The page comes
/// from the app bundle through the `marina://` scheme, never the network, and
/// only animates her: the app does all the talking to the bridge.
@MainActor
final class AvatarController: NSObject, ObservableObject, WKScriptMessageHandler, WKNavigationDelegate {
    @Published var ready = false
    @Published var problem: String?

    let webView: WKWebView

    override init() {
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(BundleSchemeHandler(), forURLScheme: "marina")
        config.mediaTypesRequiringUserActionForPlayback = []   // her voice plays without a tap in the page
        config.allowsInlineMediaPlayback = true
        let content = WKUserContentController()
        config.userContentController = content
        webView = WKWebView(frame: .zero, configuration: config)
        super.init()
        content.add(WeakHandler(self), name: "marina")

        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.bounces = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.isUserInteractionEnabled = false
        webView.navigationDelegate = self
        #if DEBUG
        if #available(iOS 16.4, *) { webView.isInspectable = true }
        #endif
        webView.load(URLRequest(url: URL(string: "marina://app/index.html")!))
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        switch body["type"] as? String {
        case "ready": ready = true; problem = nil; NSLog("[avatar] ready")
        case "error":
            problem = body["message"] as? String
            NSLog("[avatar] error: %@", problem ?? "?")
        case "log": NSLog("[avatar] %@: %@", body["level"] as? String ?? "log", body["message"] as? String ?? "")
        default: break
        }
    }

    /// iOS can kill the page's process (memory, or the app sitting in the
    /// background); bring her back rather than leaving an empty space.
    private var reloads = 0
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        NSLog("[avatar] web content process ended; reloading")
        ready = false
        reloads += 1
        guard reloads <= 3 else { problem = "Her avatar keeps crashing on this phone."; return }
        webView.reload()
    }

    // MARK: driving her

    private func call(_ js: String, _ args: [String: Any] = [:]) async {
        _ = try? await webView.callAsyncJavaScript(js, arguments: args, contentWorld: .page)
    }

    /// Starts the page's audio; true once it is actually running. iOS can
    /// leave it "interrupted" after our own player has used the audio session.
    func unlockAudio() async -> Bool {
        for attempt in 0..<6 {
            let state = try? await webView.callAsyncJavaScript(
                "return await window.marinaAvatar?.unlock()", arguments: [:], contentWorld: .page) as? String
            if state == "running" { return true }
            if attempt < 5 { try? await Task.sleep(for: .milliseconds(250)) }
        }
        NSLog("[avatar] page audio would not start; her voice plays natively this reply")
        return false
    }
    func begin() async { await call("window.marinaAvatar?.begin()") }
    func chunk(_ event: BridgeEvent) async { await call("return await window.marinaAvatar?.chunk(ev)", ["ev": event.raw]) }
    func end() async { await call("return await window.marinaAvatar?.end()") }
    func stop() async { await call("window.marinaAvatar?.stop()") }
    /// A sentence she isn't voicing here: just its actions and mood, no audio.
    func act(_ event: BridgeEvent) async {
        var ev = event.raw
        ev["audio"] = nil
        await call("window.marinaAvatar?.act(ev)", ["ev": ev])
    }
}

/// Keeps the controller from being retained by its own web view.
private final class WeakHandler: NSObject, WKScriptMessageHandler {
    weak var target: (any WKScriptMessageHandler)?
    init(_ target: any WKScriptMessageHandler) { self.target = target }
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        target?.userContentController(c, didReceive: m)
    }
}

/// Serves `marina://app/<path>` from the bundle: the renderer folder copied
/// from app/renderer, plus ios-shim.js and model.vrm at the bundle root.
private final class BundleSchemeHandler: NSObject, WKURLSchemeHandler {
    func webView(_ webView: WKWebView, start task: any WKURLSchemeTask) {
        guard let url = task.request.url else { return }
        var path = url.path
        if path.hasPrefix("/") { path.removeFirst() }
        if path.isEmpty { path = "index.html" }

        let bundle = Bundle.main
        let file: URL?
        switch path {
        case "ios-shim.js", "model.vrm", "mocap.bin":
            file = bundle.url(forResource: path, withExtension: nil)
        default:
            file = bundle.resourceURL?.appendingPathComponent("renderer").appendingPathComponent(path)
        }

        guard let file, var data = try? Data(contentsOf: file) else {
            task.didFailWithError(URLError(.fileDoesNotExist))
            return
        }
        if path == "index.html", var html = String(data: data, encoding: .utf8) {
            html = html.replacingOccurrences(
                of: "<head>",
                with: "<head>\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n  <script src=\"ios-shim.js\"></script>",
                options: [], range: html.range(of: "<head>"))
            data = Data(html.utf8)
        }
        let mime: String
        switch file.pathExtension.lowercased() {
        case "html": mime = "text/html"
        case "js": mime = "text/javascript"
        case "css": mime = "text/css"
        case "vrm", "glb": mime = "model/gltf-binary"
        case "json", "webmanifest": mime = "application/json"
        default: mime = UTType(filenameExtension: file.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
        }
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Type": mime,
                                                      "Content-Length": String(data.count),
                                                      "Cache-Control": "no-cache"])!
        task.didReceive(response)
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: any WKURLSchemeTask) {}
}

struct AvatarView: UIViewRepresentable {
    let controller: AvatarController
    func makeUIView(context: Context) -> WKWebView { controller.webView }
    func updateUIView(_ view: WKWebView, context: Context) {}
}
