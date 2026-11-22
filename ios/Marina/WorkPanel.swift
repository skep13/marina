import SwiftUI

/// While she works: what she's doing step by step, a live look at the
/// machine's screen, and a Stop button. Afterwards it folds into a line you
/// can open to see what she did.
struct WorkPanel: View {
    @EnvironmentObject var chat: Chat
    @State private var open = false
    @State private var shot: UIImage?
    @State private var showScreen = false

    private var onMachine: Bool { chat.steps.contains { $0.where_ == "vm" } }
    private var place: String {
        chat.steps.last?.where_ == "mac" ? "your Mac" : (chat.workspace ?? "her machine")
    }

    var body: some View {
        if !chat.steps.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                header
                if chat.working || open {
                    if onMachine { screen }
                    steps
                }
            }
            .padding(12)
            .background(Color.panel.opacity(0.92), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .padding(.horizontal, 12)
            .padding(.top, 4)
            .animation(.spring(duration: 0.3), value: chat.working)
            .animation(.spring(duration: 0.3), value: open)
            .task(id: chat.working) { await refresh() }
            .sheet(isPresented: $showScreen) { ScreenSheet(title: place) }
        }
    }

    private var header: some View {
        HStack(spacing: 8) {
            if chat.working {
                ProgressView().controlSize(.small).tint(.accent)
                Text("Working on \(place)").font(.subheadline.weight(.semibold))
                Spacer()
                Button(role: .destructive) { chat.stop() } label: {
                    Label("Stop", systemImage: "stop.fill").font(.footnote.weight(.semibold))
                        .padding(.horizontal, 10).padding(.vertical, 5)
                        .background(Color.red.opacity(0.85), in: Capsule())
                        .foregroundStyle(.white)
                }
                .accessibilityLabel("Stop her")
            } else {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                Text("\(chat.steps.count) \(chat.steps.count == 1 ? "step" : "steps") on \(place)")
                    .font(.subheadline)
                Spacer()
                Button(open ? "Hide" : "Show") { open.toggle() }.font(.footnote)
            }
        }
    }

    private var screen: some View {
        Button { showScreen = true } label: {
            ZStack {
                RoundedRectangle(cornerRadius: 10).fill(Color.black.opacity(0.4))
                if let shot {
                    Image(uiImage: shot).resizable().scaledToFit()
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                } else {
                    ProgressView().tint(.secondary)
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 110)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("See \(place)'s screen")
    }

    private var steps: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(chat.steps.suffix(open && !chat.working ? 30 : 4)) { step in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Image(systemName: step.done ? "checkmark" : "arrow.right")
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(step.done ? Color.secondary : Color.accent)
                        .frame(width: 12)
                    Text(step.text).font(.caption).lineLimit(2)
                        .foregroundStyle(step.done ? .secondary : .primary)
                }
            }
        }
    }

    /// Every few seconds while she works, and once when it's opened after.
    private func refresh() async {
        guard onMachine || chat.working else { return }
        repeat {
            if onMachine, let image = await chat.screen() { shot = image }
            try? await Task.sleep(for: .seconds(4))
        } while chat.working && !Task.isCancelled
    }
}

/// The machine's screen full size, pinch to zoom, refreshed on pull.
struct ScreenSheet: View {
    @EnvironmentObject var chat: Chat
    @Environment(\.dismiss) private var dismiss
    let title: String
    @State private var image: UIImage?
    @State private var scale: CGFloat = 1
    @State private var settled: CGFloat = 1

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()
                if let image {
                    ScrollView([.horizontal, .vertical]) {
                        Image(uiImage: image).resizable().scaledToFit()
                            .frame(width: UIScreen.main.bounds.width * scale)
                    }
                    .gesture(MagnifyGesture()
                        .onChanged { scale = max(1, min(settled * $0.magnification, 5)) }
                        .onEnded { _ in settled = scale })
                } else {
                    ProgressView().tint(.white)
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { image = nil; image = await chat.screen(full: true) } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .task {
                while !Task.isCancelled {
                    if let fresh = await chat.screen(full: true) { image = fresh }
                    try? await Task.sleep(for: .seconds(5))
                }
            }
        }
        .preferredColorScheme(.dark)
    }
}
