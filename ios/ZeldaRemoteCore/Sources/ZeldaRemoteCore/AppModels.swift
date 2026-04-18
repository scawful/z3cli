import Foundation

public struct ZRModelInfo: Equatable, Sendable, Identifiable {
    public var id: String { modelId }
    public let name: String
    public let modelId: String
    public let role: String
    public let loaded: Bool
    public let toolsEnabled: Bool

    public init(name: String, modelId: String, role: String, loaded: Bool, toolsEnabled: Bool) {
        self.name = name
        self.modelId = modelId
        self.role = role
        self.loaded = loaded
        self.toolsEnabled = toolsEnabled
    }

    public static func from(dictionary d: [String: Any]) -> ZRModelInfo? {
        let name = (d["name"] as? String) ?? ""
        let modelId = (d["model_id"] as? String) ?? name
        if name.isEmpty && modelId.isEmpty { return nil }
        let role = (d["role"] as? String) ?? ""
        let loaded = (d["loaded"] as? Bool) ?? (d["loaded"] as? NSNumber)?.boolValue ?? false
        let toolsEnabled = (d["tools_enabled"] as? Bool)
            ?? (d["tools_enabled"] as? NSNumber)?.boolValue ?? false
        return ZRModelInfo(
            name: name,
            modelId: modelId,
            role: role,
            loaded: loaded,
            toolsEnabled: toolsEnabled
        )
    }
}

public struct ZRAppConfig: Equatable, Sendable {
    public let version: String
    public let backend: String
    public let activeModel: String
    public let studioModel: String?
    public let mode: String
    public let workspace: String
    public let romPath: String
    public let toolsEnabled: Bool
    public let toolsWrite: Bool?
    public let servers: [String]
    public let toolCount: Int
    public let warnings: [String]
    public let models: [ZRModelInfo]
    public let sessionPath: String
    public let focusFile: String?
    public let broadcastModels: [String]
    public var permissionRules: [String: Bool]?

    public init(params p: [String: Any]) {
        version = (p["version"] as? String) ?? ""
        backend = (p["backend"] as? String) ?? ""
        activeModel = (p["active_model"] as? String) ?? ""
        studioModel = p["studio_model"] as? String
        mode = (p["mode"] as? String) ?? ""
        workspace = (p["workspace"] as? String) ?? ""
        romPath = (p["rom_path"] as? String) ?? ""
        toolsEnabled = (p["tools_enabled"] as? Bool) ?? (p["tools_enabled"] as? NSNumber)?.boolValue ?? false
        toolsWrite = (p["tools_write"] as? Bool) ?? (p["tools_write"] as? NSNumber)?.boolValue
        servers = (p["servers"] as? [String]) ?? []
        toolCount = ParsedRPC.intValue(p["tool_count"]) ?? 0
        warnings = (p["warnings"] as? [String]) ?? []
        if let rawModels = p["models"] as? [[String: Any]] {
            models = rawModels.compactMap { ZRModelInfo.from(dictionary: $0) }
        } else {
            models = []
        }
        sessionPath = (p["session_path"] as? String) ?? ""
        focusFile = p["focus_file"] as? String
        broadcastModels = (p["broadcast_models"] as? [String]) ?? []
        permissionRules = p["permission_rules"] as? [String: Bool]
    }

    /// Copy with updated permission rules (session allow/deny).
    public func withPermissionRules(_ rules: [String: Bool]?) -> ZRAppConfig {
        ZRAppConfig(
            version: version,
            backend: backend,
            activeModel: activeModel,
            studioModel: studioModel,
            mode: mode,
            workspace: workspace,
            romPath: romPath,
            toolsEnabled: toolsEnabled,
            toolsWrite: toolsWrite,
            servers: servers,
            toolCount: toolCount,
            warnings: warnings,
            models: models,
            sessionPath: sessionPath,
            focusFile: focusFile,
            broadcastModels: broadcastModels,
            permissionRules: rules
        )
    }

    private init(
        version: String,
        backend: String,
        activeModel: String,
        studioModel: String?,
        mode: String,
        workspace: String,
        romPath: String,
        toolsEnabled: Bool,
        toolsWrite: Bool?,
        servers: [String],
        toolCount: Int,
        warnings: [String],
        models: [ZRModelInfo],
        sessionPath: String,
        focusFile: String?,
        broadcastModels: [String],
        permissionRules: [String: Bool]?
    ) {
        self.version = version
        self.backend = backend
        self.activeModel = activeModel
        self.studioModel = studioModel
        self.mode = mode
        self.workspace = workspace
        self.romPath = romPath
        self.toolsEnabled = toolsEnabled
        self.toolsWrite = toolsWrite
        self.servers = servers
        self.toolCount = toolCount
        self.warnings = warnings
        self.models = models
        self.sessionPath = sessionPath
        self.focusFile = focusFile
        self.broadcastModels = broadcastModels
        self.permissionRules = permissionRules
    }
}

public struct ZRMessage: Equatable, Sendable, Identifiable {
    public let id: String
    public let role: String
    public let content: String
    /// Unix time in seconds (backend sends ms since epoch).
    public let timestamp: TimeInterval
    public let model: String?
    public let toolName: String?
    public let toolServer: String?
    public let toolArguments: String?

    public init(
        id: String,
        role: String,
        content: String,
        timestamp: TimeInterval,
        model: String? = nil,
        toolName: String? = nil,
        toolServer: String? = nil,
        toolArguments: String? = nil
    ) {
        self.id = id
        self.role = role
        self.content = content
        self.timestamp = timestamp
        self.model = model
        self.toolName = toolName
        self.toolServer = toolServer
        self.toolArguments = toolArguments
    }

    public static func fromNotificationParams(_ p: [String: Any]) -> ZRMessage {
        let id = (p["id"] as? String) ?? "msg-\(UUID().uuidString)"
        let role = (p["role"] as? String) ?? "system"
        let content = (p["content"] as? String) ?? ""
        let rawMs: Double
        if let n = p["timestamp"] as? Double {
            rawMs = n
        } else if let n = p["timestamp"] as? Int {
            rawMs = Double(n)
        } else if let n = p["timestamp"] as? NSNumber {
            rawMs = n.doubleValue
        } else {
            rawMs = Date().timeIntervalSince1970 * 1000.0
        }
        let ts = rawMs / 1000.0
        return ZRMessage(
            id: id,
            role: role,
            content: content,
            timestamp: ts,
            model: p["model"] as? String,
            toolName: p["tool_name"] as? String,
            toolServer: p["tool_server"] as? String,
            toolArguments: p["tool_arguments"] as? String
        )
    }
}

public struct ZRPendingPermission: Equatable, Sendable {
    public let name: String
    public let server: String
    public let arguments: String

    public init(name: String, server: String, arguments: String) {
        self.name = name
        self.server = server
        self.arguments = arguments
    }

    public static func from(params p: [String: Any]) -> ZRPendingPermission? {
        guard let name = p["name"] as? String else { return nil }
        return ZRPendingPermission(
            name: name,
            server: (p["server"] as? String) ?? "",
            arguments: (p["arguments"] as? String) ?? ""
        )
    }

    public var ruleKey: String {
        server.isEmpty ? name : "\(server):\(name)"
    }
}
