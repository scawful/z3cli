import Foundation

/// Persists bridge URL and token so the Connect tab is pre-filled on next launch.
public enum BridgeConnectionDefaults {
    private static let urlKey = "org.z3cli.zeldaRemote.bridgeWsURL"
    private static let tokenKey = "org.z3cli.zeldaRemote.bridgeToken"

    public static func loadURL() -> String {
        (UserDefaults.standard.string(forKey: urlKey) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public static func loadToken() -> String {
        (UserDefaults.standard.string(forKey: tokenKey) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public static func save(url: String, token: String) {
        UserDefaults.standard.set(url.trimmingCharacters(in: .whitespacesAndNewlines), forKey: urlKey)
        UserDefaults.standard.set(token, forKey: tokenKey)
    }
}
