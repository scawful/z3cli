import Foundation

/// WebSocket client: one text frame = one NDJSON line (same as stdio serve).
@MainActor
public final class BackendClient {
    private var session: URLSession?
    private var webSocket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var nextId = 1
    private var pending: [Int: CheckedContinuation<Any?, Error>] = [:]
    private var lineBuffer = ""

    public var onNotification: ((ParsedRPC) -> Void)?

    public init() {}

    public var isConnected: Bool { webSocket != nil }

    public func connect(url: URL, bearerToken: String) {
        disconnect()
        let cfg = URLSessionConfiguration.default
        let sess = URLSession(configuration: cfg)
        session = sess
        var request = URLRequest(url: url)
        request.setValue("Bearer \(bearerToken)", forHTTPHeaderField: "Authorization")
        let task = sess.webSocketTask(with: request)
        webSocket = task
        task.resume()
        receiveTask = Task { await self.receiveLoop() }
    }

    public func disconnect() {
        receiveTask?.cancel()
        receiveTask = nil
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        session?.invalidateAndCancel()
        session = nil
        lineBuffer = ""
        for (_, cont) in pending {
            cont.resume(throwing: BackendClientError.disconnected)
        }
        pending.removeAll()
    }

    private func receiveLoop() async {
        while !Task.isCancelled {
            guard let ws = webSocket else { break }
            do {
                let message = try await ws.receive()
                switch message {
                case let .string(text):
                    await handleIncomingChunk(text)
                case let .data(data):
                    if let text = String(data: data, encoding: .utf8) {
                        await handleIncomingChunk(text)
                    }
                @unknown default:
                    break
                }
            } catch {
                break
            }
        }
    }

    private func handleIncomingChunk(_ chunk: String) async {
        lineBuffer.append(chunk)
        while let range = lineBuffer.range(of: "\n") {
            let line = String(lineBuffer[..<range.lowerBound])
            lineBuffer.removeSubrange(..<range.upperBound)
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            guard let parsed = ParsedRPC.parseLine(trimmed) else { continue }
            switch parsed {
            case let .response(id, result):
                if let cont = pending.removeValue(forKey: id) {
                    cont.resume(returning: result)
                }
            case let .rpcError(id, message):
                if let cont = pending.removeValue(forKey: id) {
                    cont.resume(throwing: BackendClientError.rpcError(message))
                }
            case .notification:
                onNotification?(parsed)
            }
        }
    }

    private func sendJSONObject(_ obj: [String: Any]) async throws {
        guard let ws = webSocket else {
            throw BackendClientError.disconnected
        }
        let data = try JSONSerialization.data(withJSONObject: obj, options: [])
        guard let line = String(data: data, encoding: .utf8) else {
            throw BackendClientError.encoding
        }
        try await ws.send(.string(line))
    }

    /// Fire-and-forget JSON-RPC notification (no `id`).
    public func notify(method: String, params: [String: Any]? = nil) async throws {
        var obj: [String: Any] = ["jsonrpc": "2.0", "method": method]
        if let params {
            obj["params"] = params
        }
        try await sendJSONObject(obj)
    }

    public func request(method: String, params: [String: Any]? = nil) async throws -> Any? {
        guard webSocket != nil else {
            throw BackendClientError.disconnected
        }
        let id = nextId
        nextId += 1
        return try await withCheckedThrowingContinuation { continuation in
            pending[id] = continuation
            Task {
                do {
                    var obj: [String: Any] = ["jsonrpc": "2.0", "id": id, "method": method]
                    if let params {
                        obj["params"] = params
                    }
                    try await self.sendJSONObject(obj)
                } catch {
                    self.pending.removeValue(forKey: id)
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    public func chat(message: String, model: String? = nil) async throws {
        var params: [String: Any] = ["message": message]
        if let model {
            params["model"] = model
        }
        try await notify(method: "chat", params: params)
    }

    public func command(cmd: String, args: [String] = []) async throws -> Any? {
        try await request(method: "command", params: ["cmd": cmd, "args": args])
    }

    public func cancelStream() async throws {
        try await notify(method: "cancel")
    }

    public func shutdownBackend() async throws {
        try await notify(method: "shutdown")
    }
}

public enum BackendClientError: Error, LocalizedError {
    case disconnected
    case encoding
    case rpcError(String)

    public var errorDescription: String? {
        switch self {
        case .disconnected:
            return "Not connected to bridge."
        case .encoding:
            return "Failed to encode JSON."
        case let .rpcError(message):
            return message
        }
    }
}
