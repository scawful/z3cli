import Foundation

/// One NDJSON line from z3cli serve / bridge, decoded from JSON.
public enum ParsedRPC {
    case response(id: Int, result: Any?)
    case rpcError(id: Int, message: String)
    case notification(method: String, params: [String: Any])

    public static func parseLine(_ line: String) -> ParsedRPC? {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              let data = trimmed.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return nil
        }

        if let method = obj["method"] as? String {
            let params = obj["params"] as? [String: Any] ?? [:]
            return .notification(method: method, params: params)
        }

        if let id = intValue(obj["id"]) {
            if let err = obj["error"] as? [String: Any],
               let msg = err["message"] as? String
            {
                return .rpcError(id: id, message: msg)
            }
            return .response(id: id, result: obj["result"])
        }

        return nil
    }

    public static func intValue(_ any: Any?) -> Int? {
        switch any {
        case let i as Int:
            return i
        case let n as NSNumber:
            return n.intValue
        default:
            return nil
        }
    }
}
