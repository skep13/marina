import SwiftUI

extension Color {
    static let backdrop = Color(red: 0.078, green: 0.086, blue: 0.11)      // #14161c, the phone page's
    static let panel = Color(red: 0.13, green: 0.145, blue: 0.19)
    static let accent = Color(red: 0.98, green: 0.55, blue: 0.62)          // her pink
    static let dusk = Color(red: 0.55, green: 0.45, blue: 0.95)            // the violet in her sky
    static let night = Color(red: 0.06, green: 0.07, blue: 0.13)
}

struct ContentView: View {
    @EnvironmentObject var chat: Chat
    @EnvironmentObject var avatar: AvatarController
    @State private var showSettings = false
    @State private var showAvatar = true

    var body: some View {
        ZStack {
            NightSky(lively: chat.busy).ignoresSafeArea()

            VStack(spacing: 0) {
                TopBar(showSettings: $showSettings, showAvatar: $showAvatar)
                if showAvatar {
                    ZStack(alignment: .bottom) {
                        Halo(bright: chat.busy)
                        AvatarView(controller: avatar)
                            .opacity(avatar.ready ? 1 : 0)
                            .scaleEffect(avatar.ready ? 1 : 0.96, anchor: .bottom)
                            .animation(.easeOut(duration: 0.8), value: avatar.ready)
                            // No box: she fades into the chat below.
                            .mask(LinearGradient(stops: [.init(color: .black, location: 0),
                                                         .init(color: .black, location: 0.8),
                                                         .init(color: .clear, location: 1)],
                                                 startPoint: .top, endPoint: .bottom))
                        if !avatar.ready {
                            Group {
                                if let problem = avatar.problem {
                                    Text(problem).font(.footnote).foregroundStyle(.secondary)
                                        .multilineTextAlignment(.center).padding(.horizontal, 40)
                                } else {
                                    ProgressView().tint(.secondary)
                                }
                            }
                            .frame(maxHeight: .infinity)
                        }
                    }
                    .containerRelativeFrame(.vertical) { h, _ in h * 0.46 }
                    .transition(.move(edge: .top).combined(with: .opacity))
                }
                Transcript()
                WorkPanel()
                Composer()
            }
        }
        .sheet(isPresented: $showSettings) { SettingsView() }
        .alert(item: $chat.ask) { ask in
            Alert(title: Text(ask.where_ == "mac" ? "On your Mac" : "On \(chat.workspace ?? "her machine")"),
                  message: Text(ask.text),
                  primaryButton: .default(Text("Allow")) { chat.answer(true) },
                  secondaryButton: .cancel(Text("Deny")) { chat.answer(false) })
        }
    }
}

struct TopBar: View {
    @EnvironmentObject var chat: Chat
    @EnvironmentObject var handsFree: HandsFree
    @Binding var showSettings: Bool
    @Binding var showAvatar: Bool

    var body: some View {
        HStack(spacing: 10) {
            Circle().fill(dotColour).frame(width: 8, height: 8)
                .shadow(color: dotColour, radius: 4)
            VStack(alignment: .leading, spacing: 1) {
                Text("Marina").font(.headline)
                Text(statusText).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            Button { chat.toggleHandsFree() } label: {
                Image(systemName: handsFree.on ? "ear.fill" : "ear")
                    .foregroundStyle(handsFree.on ? Color.accent : Color.primary)
                    .symbolEffect(.pulse, isActive: handsFree.state == .hearing)
            }
            .accessibilityLabel(handsFree.on ? "Turn hands-free off" : "Turn hands-free on")
            Button { withAnimation(.spring(duration: 0.35)) { showAvatar.toggle() } } label: {
                Image(systemName: showAvatar ? "person.crop.circle.fill" : "person.crop.circle")
            }
            .accessibilityLabel(showAvatar ? "Hide her" : "Show her")
            Button { chat.voiceOn.toggle() } label: {
                Image(systemName: chat.voiceOn ? "speaker.wave.2.fill" : "speaker.slash")
            }
            .accessibilityLabel(chat.voiceOn ? "Mute her voice" : "Turn her voice on")
            Menu {
                if chat.presets.count > 1 {
                    Picker(selection: Binding(get: { chat.preset }, set: { chat.setPreset($0) })) {
                        ForEach(chat.presets) { Text($0.label).tag($0.name) }
                    } label: { Label("Personality", systemImage: "theatermasks") }
                    .pickerStyle(.menu)
                }
                Button("Settings", systemImage: "gearshape") { showSettings = true }
                Button("Forget this conversation", systemImage: "arrow.counterclockwise", role: .destructive) { chat.forget() }
            } label: { Image(systemName: "ellipsis.circle") }
        }
        .font(.title3)
        .foregroundStyle(.primary)
        .padding(.leading, 16).padding(.trailing, 12)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial.opacity(0.7), in: Capsule())
        .overlay(Capsule().strokeBorder(.white.opacity(0.08)))
        .padding(.horizontal, 12)
        .padding(.top, 4)
        .zIndex(1)
    }

    private var dotColour: Color {
        switch chat.link {
        case .ok: return chat.busy ? .accent : .green
        case .down: return .red
        case .unknown: return .gray
        }
    }

    private var statusText: String {
        switch chat.link {
        case .ok(let model):
            if chat.busy { return "typing…" }
            switch handsFree.state {
            case .hearing: return "hearing you…"
            case .waiting: return "listening…"
            case .listening: return "say \u{201C}Marina\u{201D} · \(handsFree.input)"
            case .off: return model
            }
        case .down(let why): return why
        case .unknown: return "connecting…"
        }
    }
}

struct Transcript: View {
    @EnvironmentObject var chat: Chat

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 8) {
                    if chat.messages.isEmpty {
                        Text(emptyText)
                            .font(.callout).foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.top, 40).padding(.horizontal, 32)
                    }
                    ForEach(chat.messages) { m in
                        Bubble(message: m).id(m.id)
                    }
                    Color.clear.frame(height: 1).id("end")
                }
                .padding(.horizontal, 14)
                .padding(.top, 6)
            }
            .scrollDismissesKeyboard(.interactively)
            .mask(LinearGradient(stops: [.init(color: .clear, location: 0), .init(color: .black, location: 0.06),
                                         .init(color: .black, location: 1)],
                                 startPoint: .top, endPoint: .bottom))
            .onChange(of: chat.messages) { _, _ in
                withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("end", anchor: .bottom) }
            }
            .onAppear { proxy.scrollTo("end", anchor: .bottom) }
        }
    }

    private var emptyText: String {
        if case .down(let why) = chat.link {
            if why.hasPrefix("Add the bridge") || why.contains("token") {
                return "\(why)\n\n⋯ › Settings."
            }
            return "She's not reachable right now. Check Tailscale is on, then pull her settings up from ⋯."
        }
        return "Say something to her."
    }
}

struct Bubble: View {
    let message: Message

    var body: some View {
        switch message.role {
        case .note:
            Text(message.text)
                .font(.footnote).foregroundStyle(.secondary)
                .frame(maxWidth: .infinity)
                .multilineTextAlignment(.center)
                .padding(.vertical, 2)
        case .you, .marina:
            let mine = message.role == .you
            HStack {
                if mine { Spacer(minLength: 48) }
                Text(rendered)
                    .font(.body)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background {
                        let shape = UnevenRoundedRectangle(cornerRadii: .init(topLeading: 18, bottomLeading: mine ? 18 : 5,
                                                                               bottomTrailing: mine ? 5 : 18, topTrailing: 18),
                                                           style: .continuous)
                        if mine {
                            shape.fill(LinearGradient(colors: [Color.accent, Color(red: 0.93, green: 0.5, blue: 0.75)],
                                                      startPoint: .topLeading, endPoint: .bottomTrailing))
                        } else {
                            shape.fill(.ultraThinMaterial).overlay(shape.fill(Color.panel.opacity(0.55)))
                                .overlay(shape.strokeBorder(.white.opacity(0.07)))
                        }
                    }
                    .foregroundStyle(mine ? Color.black : Color.primary)
                    .overlay(alignment: .bottomTrailing) {
                        if message.live && message.text.isEmpty { TypingDots().padding(10) }
                    }
                    .frame(minWidth: message.live && message.text.isEmpty ? 54 : 0,
                           minHeight: 38, alignment: .leading)
                    .textSelection(.enabled)
                if !mine { Spacer(minLength: 48) }
            }
        }
    }

    /// Her *stage directions* in italics, like the Mac app's captions.
    private var rendered: AttributedString {
        var out = AttributedString()
        var italic = false
        for part in message.text.split(separator: "*", omittingEmptySubsequences: false) {
            var piece = AttributedString(String(part))
            if italic { piece.font = .body.italic(); piece.foregroundColor = .secondary }
            out += piece
            italic.toggle()
        }
        return out
    }
}

struct TypingDots: View {
    @State private var on = false
    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<3) { i in
                Circle().frame(width: 6, height: 6)
                    .opacity(on ? 1 : 0.3)
                    .animation(.easeInOut(duration: 0.6).repeatForever().delay(Double(i) * 0.2), value: on)
            }
        }
        .foregroundStyle(.secondary)
        .onAppear { on = true }
    }
}

struct Composer: View {
    @EnvironmentObject var chat: Chat
    @EnvironmentObject var recorder: Recorder
    @State private var text = ""
    @FocusState private var focused: Bool
    @State private var pressing = false

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            if recorder.recording {
                HStack(spacing: 8) {
                    Circle().fill(.red).frame(width: 10, height: 10)
                    Text("Recording… let go to send").font(.callout)
                    Spacer()
                    Capsule().fill(Color.accent)
                        .frame(width: 8 + CGFloat(recorder.level) * 60, height: 6)
                        .animation(.linear(duration: 0.08), value: recorder.level)
                }
                .padding(.horizontal, 14).frame(height: 44)
                .background(Color.panel, in: Capsule())
            } else {
                TextField("Message Marina", text: $text, axis: .vertical)
                    .lineLimit(1...5)
                    .focused($focused)
                    .submitLabel(.send)
                    .onSubmit(send)
                    .padding(.horizontal, 16).padding(.vertical, 11)
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous)
                        .strokeBorder(focused ? Color.accent.opacity(0.6) : .white.opacity(0.08)))
                    .animation(.easeOut(duration: 0.2), value: focused)
            }

            if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                micButton
            } else {
                Button(action: send) {
                    Image(systemName: "arrow.up").font(.headline)
                        .frame(width: 44, height: 44)
                        .background(Color.accent, in: Circle())
                        .foregroundStyle(.black)
                        .shadow(color: Color.accent.opacity(0.5), radius: 8)
                }
                .transition(.scale.combined(with: .opacity))
                .accessibilityLabel("Send")
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, 6)
        .padding(.bottom, 8)
        .animation(.spring(duration: 0.3), value: text.isEmpty)
    }

    private var micButton: some View {
        Image(systemName: recorder.recording ? "mic.fill" : "mic")
            .font(.headline)
            .frame(width: 44, height: 44)
            .background(recorder.recording ? AnyShapeStyle(Color.red) : AnyShapeStyle(.ultraThinMaterial), in: Circle())
            .overlay(Circle().strokeBorder(.white.opacity(recorder.recording ? 0 : 0.08)))
            .scaleEffect(recorder.recording ? 1.15 : 1)
            .animation(.spring(duration: 0.25), value: recorder.recording)
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        guard !pressing else { return }
                        pressing = true
                        Task { _ = await recorder.start() }
                    }
                    .onEnded { value in
                        pressing = false
                        // Slide away to cancel, like a voice note.
                        if abs(value.translation.width) > 80 || abs(value.translation.height) > 80 {
                            recorder.cancel()
                        } else if let clip = recorder.stop() {
                            chat.sendVoice(clip)
                        }
                    }
            )
            .accessibilityLabel("Hold to record a voice note")
    }

    private func send() {
        let t = text
        text = ""
        chat.send(t)
    }
}


/// Her sky: dusk-to-night with slow-twinkling stars drifting upwards, a nod
/// to the moon on her shirt. Livelier while she's answering.
struct NightSky: View {
    var lively = false

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.13, green: 0.11, blue: 0.24), .night, Color(red: 0.04, green: 0.05, blue: 0.08)],
                           startPoint: .top, endPoint: .bottom)
            TimelineView(.animation(minimumInterval: 1.0 / 30)) { tl in
                let t = tl.date.timeIntervalSinceReferenceDate
                Canvas { ctx, size in
                    for i in 0..<70 {
                        // Fixed pseudo-random place, size and rhythm per star.
                        func r(_ k: Double) -> Double { let x = sin(Double(i) * 12.9898 + k * 78.233) * 43758.5453; return x - x.rounded(.down) }
                        let speed = 4 + r(1) * 8
                        let y = (r(2) * size.height - t * speed).truncatingRemainder(dividingBy: size.height)
                        let p = CGPoint(x: r(3) * size.width + sin(t * 0.2 + r(4) * 6) * 6,
                                        y: y < 0 ? y + size.height : y)
                        let twinkle = 0.5 + 0.5 * sin(t * (0.6 + r(5) * 1.6) + r(6) * 6.28)
                        let d = 1 + r(7) * 2.2
                        let warm = r(8) > 0.8
                        ctx.opacity = (0.15 + 0.6 * twinkle) * (1 - p.y / size.height * 0.6)
                        ctx.fill(Path(ellipseIn: CGRect(x: p.x - d / 2, y: p.y - d / 2, width: d, height: d)),
                                 with: .color(warm ? Color.accent : .white))
                        if d > 2.6 {
                            ctx.opacity *= 0.25
                            ctx.fill(Path(ellipseIn: CGRect(x: p.x - d * 2, y: p.y - d * 2, width: d * 4, height: d * 4)),
                                     with: .color(warm ? Color.accent : Color.dusk))
                        }
                    }
                }
            }
            .opacity(lively ? 1 : 0.8)
            .animation(.easeInOut(duration: 1.2), value: lively)
        }
    }
}

/// A soft glow behind her that breathes, and brightens while she answers.
struct Halo: View {
    var bright = false
    @State private var breathe = false

    var body: some View {
        ZStack {
            Ellipse()
                .fill(RadialGradient(colors: [Color.dusk.opacity(0.45), Color.dusk.opacity(0.12), .clear],
                                     center: .center, startRadius: 10, endRadius: 210))
                .frame(width: 420, height: 420)
                .offset(y: -40)
            Ellipse()
                .fill(RadialGradient(colors: [Color.accent.opacity(bright ? 0.4 : 0.22), .clear],
                                     center: .center, startRadius: 0, endRadius: 150))
                .frame(width: 300, height: 260)
                .offset(y: -70)
        }
        .scaleEffect(breathe ? 1.06 : 0.96)
        .opacity(breathe ? 1 : 0.8)
        .animation(.easeInOut(duration: 4).repeatForever(autoreverses: true), value: breathe)
        .animation(.easeInOut(duration: 0.8), value: bright)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .allowsHitTesting(false)
        .onAppear { breathe = true }
    }
}
