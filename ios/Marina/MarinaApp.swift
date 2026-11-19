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
                .preferredColorScheme(.dark)
                .task { await chat.connect() }
        }
        .onChange(of: phase) { _, now in
            chat.foreground = now == .active
            if now == .active {
                UNUserNotificationCenter.current().setBadgeCount(0)
                Task { await chat.connect() }
            }
        }
    }
}

import UserNotifications
