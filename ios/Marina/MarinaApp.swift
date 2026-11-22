import SwiftUI

@main
struct MarinaApp: App {
    @StateObject private var chat = Chat(avatar: AvatarController())
    @Environment(\.scenePhase) private var phase

    init() {
        Audio.playback()
        Notifier.ask()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(chat)
                .environmentObject(chat.avatar)
                .environmentObject(chat.recorder)
                .environmentObject(chat.handsFree)
                .preferredColorScheme(.dark)
                .task {
                    #if DEBUG
                    if CommandLine.arguments.contains("-demoWork") { chat.demoWork(); return }
                    #endif
                    await chat.connect()
                    if Settings.handsFree && !chat.handsFree.on { chat.toggleHandsFree() }
                }
                .onOpenURL { _ in }   // marinaapp:// from a push: opening the app is the point
        }
        .onChange(of: phase) { _, now in
            chat.foreground = now == .active
            // Hands-free keeps her able to speak with the screen locked, so
            // she can keep talking to you here instead of pushing.
            if now == .background { chat.presence(chat.handsFree.on) }
            if now == .active {
                UNUserNotificationCenter.current().setBadgeCount(0)
                Task { await chat.connect() }
            }
        }
    }
}

import UserNotifications
