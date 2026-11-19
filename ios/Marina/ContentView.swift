import SwiftUI

extension Color {
    static let backdrop = Color(red: 0.078, green: 0.086, blue: 0.11)      // #14161c, the phone page's
    static let panel = Color(red: 0.13, green: 0.145, blue: 0.19)
    static let accent = Color(red: 0.98, green: 0.55, blue: 0.62)          // her pink
}

struct ContentView: View {
    @EnvironmentObject var chat: Chat
    @EnvironmentObject var avatar: AvatarController
    @State private var showSettings = false
    @State private var showAvatar = true

    var body: some View {
        ZStack {
            RadialGradient(colors: [Color(red: 0.15, green: 0.17, blue: 0.22), .backdrop],
                           center: .init(x: 0.5, y: 0.25), startRadius: 0, endRadius: 520)
                .ignoresSafeArea()

            VStack(spacing: 0) {
                TopBar(showSettings: $showSettings, showAvatar: $showAvatar)
                if showAvatar {
                    ZStack(alignment: .bottom) {
                        AvatarView(controller: avatar)
                            .opacity(avatar.ready ? 1 : 0)
                            .animation(.easeOut(duration: 0.6), value: avatar.ready)
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
                        if let what = chat.activity {
                            Label(what, systemImage: "gearshape.2")
                                .font(.footnote).padding(.horizontal, 12).padding(.vertical, 6)
                                .background(.ultraThinMaterial, in: Capsule())
                                .padding(.bottom, 8)
                        }
                    }
                    .frame(height: 300)
                    .transition(.move(edge: .top).combined(with: .opacity))
                }
                Transcript()
                Composer()
            }
        }
        .sheet(isPresented: $showSettings) { SettingsView() }
        .alert(item: $chat.ask) { ask in
            Alert(title: Text(ask.where_ == "mac" ? "On your Mac" : "On her machine"),
                  message: Text(ask.text),
                  primaryButton: .default(Text("Allow")) { chat.answer(true) },
                  secondaryButton: .cancel(Text("Deny")) { chat.answer(false) })
        }
    }
}

struct TopBar: View {
    @EnvironmentObject var chat: Chat
    @Binding var showSettings: Bool
    @Binding var showAvatar: Bool

    var body: some View {
        HStack(spacing: 10) {
            Circle().fill(dotColour).frame(width: 8, height: 8)
            VStack(alignment: .leading, spacing: 1) {
                Text("Marina").font(.headline)
                Text(statusText).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            Button { withAnimation(.spring(duration: 0.35)) { showAvatar.toggle() } } label: {
                Image(systemName: showAvatar ? "person.crop.circle.fill" : "person.crop.circle")
            }
            .accessibilityLabel(showAvatar ? "Hide her" : "Show her")
            Button { chat.voiceOn.toggle() } label: {
                Image(systemName: chat.voiceOn ? "speaker.wave.2.fill" : "speaker.slash")
            }
            .accessibilityLabel(chat.voiceOn ? "Mute her voice" : "Turn her voice on")
            Menu {
                Button("Settings", systemImage: "gearshape") { showSettings = true }
                Button("Forget this conversation", systemImage: "arrow.counterclockwise", role: .destructive) { chat.forget() }
            } label: { Image(systemName: "ellipsis.circle") }
        }
        .font(.title3)
        .foregroundStyle(.primary)
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
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
        case .ok(let model): return chat.busy ? "typing…" : model
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
            .onChange(of: chat.messages) { _, _ in
                withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("end", anchor: .bottom) }
            }
            .onAppear { proxy.scrollTo("end", anchor: .bottom) }
        }
    }

    private var emptyText: String {
        if case .down = chat.link { return "She's not reachable right now. Check Tailscale is on, then pull her settings up from ⋯." }
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
                    .background(mine ? Color.accent.opacity(0.85) : Color.panel,
                                in: RoundedRectangle(cornerRadius: 18, style: .continuous))
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
                    .padding(.horizontal, 14).padding(.vertical, 11)
                    .background(Color.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            }

            if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                micButton
            } else {
                Button(action: send) {
                    Image(systemName: "arrow.up").font(.headline)
                        .frame(width: 44, height: 44)
                        .background(Color.accent, in: Circle())
                        .foregroundStyle(.black)
                }
                .accessibilityLabel("Send")
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, 6)
        .padding(.bottom, 8)
        .background(.ultraThinMaterial.opacity(0.6))
    }

    private var micButton: some View {
        Image(systemName: recorder.recording ? "mic.fill" : "mic")
            .font(.headline)
            .frame(width: 44, height: 44)
            .background(recorder.recording ? Color.red : Color.panel, in: Circle())
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
