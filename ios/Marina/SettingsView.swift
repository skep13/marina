import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var chat: Chat
    @Environment(\.dismiss) private var dismiss
    @State private var url = Settings.bridgeURL
    @State private var token = Settings.token
    @State private var notify = Settings.notifyOn
    @State private var result: String?
    @State private var testing = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://lab3.tail35b6c6.ts.net", text: $url)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("Token", text: $token)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("Her bridge on lab3")
                } footer: {
                    Text("The token is the bridge's web token (/etc/appliance/phone.token on lab3). It's kept in this phone's Keychain. Away from home, turn Tailscale on.")
                }

                Section {
                    Button {
                        test()
                    } label: {
                        HStack {
                            Text("Test connection")
                            Spacer()
                            if testing { ProgressView() }
                        }
                    }
                    if let result { Text(result).font(.footnote).foregroundStyle(.secondary) }
                }

                Section {
                    Toggle("Notify me when she messages first", isOn: $notify)
                } footer: {
                    Text("Works while the app is open or recently closed. iPhone stops apps installed with a free Apple ID from getting push notifications.")
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { save(); dismiss() }
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }

    private func save() {
        Settings.bridgeURL = url
        Settings.token = token
        Settings.notifyOn = notify
        chat.reconfigure()
    }

    private func test() {
        testing = true
        result = nil
        let bridge = Bridge(baseURL: URL(string: url.trimmingCharacters(in: .whitespaces)),
                            token: token.trimmingCharacters(in: .whitespacesAndNewlines))
        Task {
            do {
                let h = try await bridge.health()
                result = "Connected · \(h["model"] as? String ?? "ok") · \(h["memories"] as? Int ?? 0) memories"
            } catch {
                result = Chat.describe(error)
            }
            testing = false
        }
    }
}
