import Combine
import Foundation

/// Ports `useBackend` state transitions for native SwiftUI.
@MainActor
public final class BackendStore: ObservableObject {
    @Published public private(set) var config: ZRAppConfig?
    @Published public private(set) var messages: [ZRMessage] = []
    @Published public private(set) var streamingContent = ""
    @Published public private(set) var streamingThinking = ""
    @Published public private(set) var isStreaming = false
    @Published public private(set) var activeToolName: String?
    @Published public private(set) var activeToolServer: String?
    @Published public private(set) var activeToolStartedAt: Date?
    @Published public private(set) var promptTokens = 0
    @Published public private(set) var completionTokens = 0
    @Published public private(set) var error: String?
    @Published public private(set) var pendingPermission: ZRPendingPermission?

    public let client = BackendClient()

    private var cancelledStreaming = false
    private var chatWaiter: CheckedContinuation<Void, Error>?
    private var messageCounter = 0

    public init() {
        client.onNotification = { [weak self] parsed in
            Task { @MainActor in
                self?.handleNotification(parsed)
            }
        }
    }

    private func nextLocalMessageId() -> String {
        messageCounter += 1
        return "local-\(messageCounter)"
    }

    public func connect(url: URL, bearerToken: String) {
        error = nil
        client.connect(url: url, bearerToken: bearerToken)
    }

    public func disconnect() {
        client.disconnect()
    }

    public func sendMessage(_ text: String) async throws {
        guard client.isConnected else {
            throw BackendClientError.disconnected
        }
        if chatWaiter != nil {
            throw NSError(
                domain: "BackendStore",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Already streaming a chat response"]
            )
        }
        cancelledStreaming = false
        streamingContent = ""
        streamingThinking = ""
        isStreaming = true
        error = nil
        messages.append(
            ZRMessage(
                id: nextLocalMessageId(),
                role: "user",
                content: text,
                timestamp: Date().timeIntervalSince1970
            )
        )
        try await client.chat(message: text)
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            chatWaiter = cont
        }
    }

    public func cancelStream() async throws {
        cancelledStreaming = true
        activeToolName = nil
        activeToolServer = nil
        activeToolStartedAt = nil
        try await client.cancelStream()
    }

    public func sendCommand(cmd: String, args: [String] = []) async throws -> Any? {
        try await client.command(cmd: cmd, args: args)
    }

    /// JSON-RPC `models` (not a slash command on the Python serve loop).
    public func fetchModelsList() async throws -> Any? {
        try await client.request(method: "models")
    }

    /// JSON-RPC `status` (same payload shape as `ready`).
    public func fetchStatusRPC() async throws -> Any? {
        try await client.request(method: "status")
    }

    public func addSystemMessage(_ content: String) {
        messages.append(
            ZRMessage(
                id: nextLocalMessageId(),
                role: "system",
                content: content,
                timestamp: Date().timeIntervalSince1970
            )
        )
    }

    public func approveTool() async throws {
        pendingPermission = nil
        _ = try await client.command(cmd: "tool/decision", args: ["allow-once"])
    }

    public func approveToolForSession() async throws {
        let key = pendingPermission?.ruleKey
        pendingPermission = nil
        _ = try await client.command(cmd: "tool/decision", args: ["allow-session"])
        if let key, let cfg = config {
            var rules = cfg.permissionRules ?? [:]
            rules[key] = true
            config = cfg.withPermissionRules(rules)
        }
    }

    public func denyTool() async throws {
        pendingPermission = nil
        _ = try await client.command(cmd: "tool/decision", args: ["deny-once"])
    }

    public func denyToolForSession() async throws {
        let key = pendingPermission?.ruleKey
        pendingPermission = nil
        _ = try await client.command(cmd: "tool/decision", args: ["deny-session"])
        if let key, let cfg = config {
            var rules = cfg.permissionRules ?? [:]
            rules[key] = false
            config = cfg.withPermissionRules(rules)
        }
    }

    private func resolveChatWaiter() {
        let waiter = chatWaiter
        chatWaiter = nil
        waiter?.resume()
    }

    private func rejectChatWaiter(_ message: String) {
        let waiter = chatWaiter
        chatWaiter = nil
        waiter?.resume(throwing: NSError(
            domain: "BackendStore",
            code: 2,
            userInfo: [NSLocalizedDescriptionKey: message]
        ))
    }

    private func handleNotification(_ parsed: ParsedRPC) {
        guard case let .notification(method, params) = parsed else { return }
        switch method {
        case "ready":
            promptTokens = intParam(params["prompt_tokens"]) ?? 0
            completionTokens = intParam(params["completion_tokens"]) ?? 0
            config = ZRAppConfig(params: params)
        case "message":
            let msg = ZRMessage.fromNotificationParams(params)
            if msg.role == "assistant" {
                streamingContent = ""
            }
            messages.append(msg)
        case "thinking":
            if !cancelledStreaming, let delta = params["delta"] as? String {
                streamingThinking += delta
            }
        case "text":
            if !cancelledStreaming, let delta = params["delta"] as? String {
                streamingContent += delta
            }
        case "tool_call":
            streamingContent = ""
            streamingThinking = ""
            activeToolName = params["name"] as? String
            activeToolServer = params["server"] as? String
            activeToolStartedAt = Date()
        case "tool_result":
            activeToolName = nil
            activeToolServer = nil
            activeToolStartedAt = nil
        case "done":
            if cancelledStreaming {
                cancelledStreaming = false
                streamingContent = ""
                streamingThinking = ""
                isStreaming = false
                activeToolName = nil
                activeToolServer = nil
                activeToolStartedAt = nil
                resolveChatWaiter()
                return
            }
            let pt = intParam(params["prompt_tokens"]) ?? 0
            let ct = intParam(params["completion_tokens"]) ?? 0
            promptTokens += pt
            completionTokens += ct
            streamingContent = ""
            streamingThinking = ""
            isStreaming = false
            activeToolName = nil
            activeToolServer = nil
            activeToolStartedAt = nil
            resolveChatWaiter()
        case "tool/permission_request":
            pendingPermission = ZRPendingPermission.from(params: params)
        case "error":
            activeToolName = nil
            activeToolServer = nil
            activeToolStartedAt = nil
            cancelledStreaming = false
            streamingContent = ""
            streamingThinking = ""
            let msg = (params["message"] as? String) ?? "Unknown error"
            error = msg
            isStreaming = false
            if chatWaiter != nil {
                rejectChatWaiter(msg)
            }
        default:
            break
        }
    }

    private func intParam(_ any: Any?) -> Int? {
        if let i = any as? Int { return i }
        if let n = any as? NSNumber { return n.intValue }
        return nil
    }
}
