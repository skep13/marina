import Foundation
import Security

/// Where her bridge is and the token it wants. The address lives in
/// UserDefaults; the token only ever goes in the Keychain.
enum Settings {
    /// lab3's Tailscale name: it reaches her bridge from anywhere on the
    /// tailnet without a subnet route (the LAN address only works at home).
    static let defaultBridge = "https://lab3.tail35b6c6.ts.net"
    private static let oldDefault = "http://192.168.1.15:8765"

    static var bridgeURL: String {
        get {
            let saved = UserDefaults.standard.string(forKey: "bridgeURL") ?? ""
            return saved.isEmpty || saved == oldDefault ? defaultBridge : saved
        }
        set { UserDefaults.standard.set(newValue.trimmingCharacters(in: .whitespacesAndNewlines), forKey: "bridgeURL") }
    }

    static var voiceOn: Bool {
        get { UserDefaults.standard.object(forKey: "voiceOn") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "voiceOn") }
    }

    static var handsFree: Bool {
        get { UserDefaults.standard.bool(forKey: "handsFree") }
        set { UserDefaults.standard.set(newValue, forKey: "handsFree") }
    }

    static var notifyOn: Bool {
        get { UserDefaults.standard.object(forKey: "notifyOn") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "notifyOn") }
    }

    /// The token built into the app (bridge.token next to project.yml, never
    /// committed), so a fresh install connects without typing it.
    static let builtInToken: String = {
        guard let url = Bundle.main.url(forResource: "bridge", withExtension: "token"),
              let text = try? String(contentsOf: url, encoding: .utf8) else { return "" }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }()

    static var token: String {
        get {
            let saved = Keychain.read("bridgeToken") ?? ""
            return saved.isEmpty ? builtInToken : saved
        }
        set { Keychain.write("bridgeToken", newValue.trimmingCharacters(in: .whitespacesAndNewlines)) }
    }
}

enum Keychain {
    private static func query(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "com.skep13.marina",
         kSecAttrAccount as String: key]
    }

    static func read(_ key: String) -> String? {
        var q = query(key)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func write(_ key: String, _ value: String) {
        SecItemDelete(query(key) as CFDictionary)
        guard !value.isEmpty else { return }
        var q = query(key)
        q[kSecValueData as String] = Data(value.utf8)
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(q as CFDictionary, nil)
    }
}
