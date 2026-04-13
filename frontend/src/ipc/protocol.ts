/**
 * JSON-RPC 2.0 protocol types for z3cli frontend <-> Python backend.
 *
 * Frontend sends requests via stdin, backend streams events via stdout.
 */

// ---------------------------------------------------------------------------
// Core JSON-RPC
// ---------------------------------------------------------------------------

export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: number;
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: { code: number; message: string };
}

export interface JsonRpcNotification {
  jsonrpc: "2.0";
  method: string;
  params?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Request methods (frontend -> backend)
// ---------------------------------------------------------------------------

export type ChatRequest = JsonRpcRequest & {
  method: "chat";
  params: { message: string; model?: string };
};

export type CommandRequest = JsonRpcRequest & {
  method: "command";
  params: { cmd: string; args: string[] };
};

export type StatusRequest = JsonRpcRequest & {
  method: "status";
};

export type ModelsRequest = JsonRpcRequest & {
  method: "models";
};

// ---------------------------------------------------------------------------
// Notification methods (backend -> frontend, streaming)
// ---------------------------------------------------------------------------

export interface TextNotification extends JsonRpcNotification {
  method: "text";
  params: { delta: string };
}

export interface ToolCallNotification extends JsonRpcNotification {
  method: "tool_call";
  params: { name: string; server: string; arguments: string };
}

export interface ToolResultNotification extends JsonRpcNotification {
  method: "tool_result";
  params: { name: string; result: string };
}

export interface DoneNotification extends JsonRpcNotification {
  method: "done";
  params: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

export interface ThinkingNotification extends JsonRpcNotification {
  method: "thinking";
  params: { delta: string };
}

export interface ErrorNotification extends JsonRpcNotification {
  method: "error";
  params: { message: string };
}

export interface ReadyNotification extends JsonRpcNotification {
  method: "ready";
  params: {
    version: string;
    backend: string;
    active_model: string;
    studio_model?: string;
    mode: string;
    workspace: string;
    rom_path: string;
    tools_enabled: boolean;
    servers: string[];
    tool_count: number;
    warnings: string[];
    models: Array<{
      name: string;
      model_id: string;
      role: string;
      loaded: boolean;
      tools_enabled: boolean;
    }>;
    session_path: string;
    focus_file?: string;
    broadcast_models?: string[];
  };
}

export interface ToolPermissionNotification extends JsonRpcNotification {
  method: "tool/permission_request";
  params: { name: string; server: string; arguments: string };
}

export type BackendEvent =
  | TextNotification
  | ThinkingNotification
  | ToolCallNotification
  | ToolResultNotification
  | DoneNotification
  | ErrorNotification
  | ReadyNotification
  | ToolPermissionNotification;

// ---------------------------------------------------------------------------
// App-level types
// ---------------------------------------------------------------------------

export type MessageRole = "user" | "assistant" | "system" | "tool";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  model?: string;
  toolName?: string;
  toolServer?: string;
  toolArguments?: string;
  timestamp: number;
}

export interface ModelInfo {
  name: string;
  modelId: string;
  role: string;
  loaded: boolean;
  toolsEnabled: boolean;
}

export interface AppConfig {
  version: string;
  backend: string;
  activeModel: string;
  studioModel?: string;
  mode: string;
  workspace: string;
  romPath: string;
  toolsEnabled: boolean;
  servers: string[];
  toolCount: number;
  warnings: string[];
  models: ModelInfo[];
  sessionPath: string;
  focusFile?: string;
  broadcastModels?: string[];
}
