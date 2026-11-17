// Rainy Day Café: a small native window around the game page.
//
// The page is served from a private cafe:// scheme instead of file:// so it
// has a stable origin, which keeps its save (localStorage) between launches.
// It talks to Marina's bridge on http://127.0.0.1:8765 like any other client.
import Cocoa
import WebKit
import AVFoundation

final class SchemeHandler: NSObject, WKURLSchemeHandler {
    let root: URL
    init(root: URL) { self.root = root }

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url else { return }
        var path = url.path
        if path.isEmpty || path == "/" { path = "/index.html" }
        let file = root.appendingPathComponent(String(path.dropFirst())).standardizedFileURL
        guard file.path.hasPrefix(root.standardizedFileURL.path),
              let data = try? Data(contentsOf: file) else {
            task.didFailWithError(NSError(domain: NSURLErrorDomain, code: NSURLErrorFileDoesNotExist))
            return
        }
        let types = ["html": "text/html", "js": "text/javascript", "css": "text/css",
                     "png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml", "wav": "audio/wav"]
        let mime = types[file.pathExtension.lowercased()] ?? "application/octet-stream"
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Type": mime, "Content-Length": "\(data.count)"])!
        task.didReceive(response)
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}
}

// The call's microphone. The page sends {cmd: start|stop|pause}; this listens, works out when you
// start and stop talking, and hands each thing you said back as a small 16 kHz WAV.
final class Mic: NSObject, WKScriptMessageHandler {
    weak var web: WKWebView?
    private let engine = AVAudioEngine()
    private var running = false, paused = true
    private var rate: Double = 48000
    private var pre: [Float] = [], clip: [Float] = []
    private var speaking = false, spoke = 0.0, silent = 0.0, talked = 0.0, noise: Float = 0.01
    private var lastLevel = Date.distantPast
    private let q = DispatchQueue(label: "cafe.mic")

    func userContentController(_ uc: WKUserContentController, didReceive msg: WKScriptMessage) {
        guard let d = msg.body as? [String: Any], let cmd = d["cmd"] as? String else { return }
        switch cmd {
        case "start": start()
        case "stop": stop()
        case "pause": let on = d["on"] as? Bool ?? true; q.async { self.paused = on; if on { self.reset() } }
        default: break
        }
    }
    private func send(_ js: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: js), let s = String(data: data, encoding: .utf8) else { return }
        DispatchQueue.main.async { self.web?.evaluateJavaScript("window.cafeMic && window.cafeMic(\(s))", completionHandler: nil) }
    }
    private func start() {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: begin()
        case .notDetermined: AVCaptureDevice.requestAccess(for: .audio) { ok in DispatchQueue.main.async { ok ? self.begin() : self.denied() } }
        default: denied()
        }
    }
    private func denied() { send(["type": "error", "message": "The café can't hear you. Allow the microphone in System Settings, Privacy & Security, Microphone. Type for now."]) }
    private func begin() {
        if running { q.async { self.paused = false }; return }
        let input = engine.inputNode, fmt = input.outputFormat(forBus: 0)
        guard fmt.sampleRate > 0 else { return send(["type": "error", "message": "No microphone found. Type instead."]) }
        rate = fmt.sampleRate
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: fmt) { [weak self] buf, _ in
            guard let self = self, let ch = buf.floatChannelData else { return }
            let n = Int(buf.frameLength), samples = Array(UnsafeBufferPointer(start: ch[0], count: n))
            self.q.async { self.feed(samples) }
        }
        do { try engine.start(); running = true; q.async { self.paused = false; self.reset() } }
        catch { send(["type": "error", "message": "Couldn't open the microphone (\(error.localizedDescription)). Type instead."]) }
    }
    private func stop() {
        guard running else { return }
        engine.inputNode.removeTap(onBus: 0); engine.stop(); running = false
        q.async { self.paused = true; self.reset() }
    }
    private func reset() { speaking = false; spoke = 0; silent = 0; talked = 0; clip = []; pre = [] }
    private func feed(_ s: [Float]) {
        let dt = Double(s.count) / rate
        var sq: Float = 0; for v in s { sq += v * v }
        let rms = s.isEmpty ? 0 : (sq / Float(s.count)).squareRoot()
        if Date().timeIntervalSince(lastLevel) > 0.05 { lastLevel = Date(); send(["type": "level", "v": paused ? 0 : Double(rms)]) }
        if paused { return }
        let th = max(0.015, noise * 3)
        if !speaking {
            pre += s; let keep = Int(rate * 0.3); if pre.count > keep { pre.removeFirst(pre.count - keep) }
            if rms > th {
                spoke += dt
                if spoke > 0.12 { speaking = true; silent = 0; talked = 0; clip = pre; send(["type": "speech"]) }
            } else { spoke = 0; noise = noise * 0.97 + rms * 0.03 }
        } else {
            clip += s; talked += dt
            silent = rms < th * 0.7 ? silent + dt : 0
            if silent > 0.9 || talked > 15 {
                let spoken = talked - silent, samples = clip
                reset()
                if spoken < 0.5 { send(["type": "short"]); return }
                send(["type": "clip", "b64": wav(samples).base64EncodedString(), "mime": "audio/wav"])
            }
        }
    }
    private func wav(_ s: [Float]) -> Data {
        let step = max(1, Int((rate / 16000).rounded())), out = Int(rate) / step
        var pcm = Data(capacity: s.count / step * 2)
        var i = 0
        while i < s.count {
            var acc: Float = 0; let e = min(s.count, i + step); for j in i..<e { acc += s[j] }
            let v = Int16(max(-1, min(1, acc / Float(e - i))) * 32767)
            withUnsafeBytes(of: v.littleEndian) { pcm.append(contentsOf: $0) }
            i += step
        }
        var h = Data()
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { h.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { h.append(contentsOf: $0) } }
        h.append("RIFF".data(using: .ascii)!); u32(UInt32(36 + pcm.count)); h.append("WAVEfmt ".data(using: .ascii)!)
        u32(16); u16(1); u16(1); u32(UInt32(out)); u32(UInt32(out * 2)); u16(2); u16(16)
        h.append("data".data(using: .ascii)!); u32(UInt32(pcm.count))
        return h + pcm
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    let mic = Mic()
    // keeps macOS from napping the café when it's in the background (on a call, another app in front)
    var awake: NSObjectProtocol?

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()

        let config = WKWebViewConfiguration()
        let root = Bundle.main.resourceURL!.appendingPathComponent("game")
        config.setURLSchemeHandler(SchemeHandler(root: root), forURLScheme: "cafe")
        config.mediaTypesRequiringUserActionForPlayback = []   // her voice plays without a click
        config.websiteDataStore = .default()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        // the café keeps running when the window is behind something or minimised
        if #available(macOS 14.0, *) { config.preferences.inactiveSchedulingPolicy = .none }
        awake = ProcessInfo.processInfo.beginActivity(options: [.userInitiatedAllowingIdleSystemSleep, .latencyCritical],
                                                      reason: "The café and calls keep going in the background")

        config.userContentController.add(mic, name: "mic")

        web = WKWebView(frame: .zero, configuration: config)
        mic.web = web
        web.uiDelegate = self
        web.navigationDelegate = self
        web.setValue(false, forKey: "drawsBackground")

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "Rainy Day Café"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.backgroundColor = NSColor(red: 0.16, green: 0.12, blue: 0.11, alpha: 1)
        window.minSize = NSSize(width: 760, height: 560)
        window.contentView = web
        window.setFrameAutosaveName("RainyDayCafeWindow")
        if !window.setFrameUsingName("RainyDayCafeWindow") { window.center() }
        window.makeKeyAndOrderFront(nil)

        web.load(URLRequest(url: URL(string: "cafe://app/index.html")!))
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    // Links to the outside world open in the real browser.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, action.navigationType == .linkActivated, url.scheme != "cafe" {
            NSWorkspace.shared.open(url); decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.runModal(); completionHandler()
    }

    @objc func reload(_ sender: Any?) { web.reload() }

    func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let app = NSMenu()
        app.addItem(withTitle: "About Rainy Day Café", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "Hide Rainy Day Café", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        app.addItem(withTitle: "Quit Rainy Day Café", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = app

        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit

        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "View")
        view.addItem(withTitle: "Reload", action: #selector(reload(_:)), keyEquivalent: "r").keyEquivalentModifierMask = [.command, .shift]
        view.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f").keyEquivalentModifierMask = [.command, .control]
        viewItem.submenu = view

        let winItem = NSMenuItem(); main.addItem(winItem)
        let win = NSMenu(title: "Window")
        win.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        winItem.submenu = win
        NSApp.windowsMenu = win

        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
