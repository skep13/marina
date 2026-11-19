import Foundation
import Security

/// Where her bridge is and the token it wants. The address lives in
/// UserDefaults; the token only ever goes in the Keychain.
enum Settings {
    static let defaultBridge = "http://192.168.1.15:8765"

    static var bridgeURL: String {
        get { UserDefaults.standard.string(forKey: "bridgeURL") ?? defaultBridge }
        set { UserDefaults.standard.set(newValue.trimmingCharacters(in: .whitespacesAndNewlines), forKey: "bridgeURL") }
    }

    static var voiceOn: Bool {
        get { UserDefaults.standard.object(forKey: "voiceOn") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "voiceOn") }
    }

    static var notifyOn: Bool {
        get { UserDefaults.standard.object(forKey: "notifyOn") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "notifyOn") }
    }

    static var token: String {
        get { Keychain.read("bridgeToken") ?? "" }
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
