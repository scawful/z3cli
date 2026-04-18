/**
 * Frontend IPC protocol facade.
 *
 * Transport-layer JSON-RPC request/notification types are generated from the
 * backend schema in `z3cli.app.ipc_schema`. This file keeps only app-local
 * view models and camelCase config/message shapes used by React state.
 */

export * from "./protocol.generated.js";

import type {
  AttachmentMeta,
  ConstructRef,
  ReadyParams,
} from "./protocol.generated.js";

// ---------------------------------------------------------------------------
// App-level types
// ---------------------------------------------------------------------------

export type MessageRole = "user" | "assistant" | "system" | "tool";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  thinking?: string;
  model?: string;
  toolName?: string;
  toolServer?: string;
  toolArguments?: string;
  timestamp: number;
  turnId?: string;
  toolGroup?: string;
  attachments?: AttachmentMeta[];
  constructRefs?: ConstructRef[];
  requestId?: string;
  spanId?: string;
}

export interface ModelInfo {
  name: string;
  modelId: string;
  role: string;
  description?: string;
  loaded: boolean;
  toolsEnabled: boolean;
  provider?: string;
  contextBudget?: number;
  loadedIdentifier?: string;
  sizeBytes?: number;
  status?: string;
  parallel?: number;
  contextLength?: number;
  maxContextLength?: number;
  architecture?: string;
  quantization?: string;
  queued?: number;
  estimatedGpuBytes?: number;
  estimatedTotalBytes?: number;
}

export interface LoadedModelInfo {
  identifier: string;
  modelKey: string;
  displayName?: string;
  sizeBytes?: number;
  architecture?: string;
  quantization?: string;
  contextLength?: number;
  maxContextLength?: number;
  parallel?: number;
  status?: string;
  queued?: number;
  ttlMs?: number;
  estimatedGpuBytes?: number;
  estimatedTotalBytes?: number;
}

export interface AppConfig {
  version: ReadyParams["version"];
  backend: ReadyParams["backend"];
  activeModel: ReadyParams["active_model"];
  studioModel?: ReadyParams["studio_model"];
  mode: ReadyParams["mode"];
  workspace: ReadyParams["workspace"];
  romPath: ReadyParams["rom_path"];
  toolsEnabled: ReadyParams["tools_enabled"];
  toolsWrite?: ReadyParams["tools_write"];
  servers: ReadyParams["servers"];
  toolCount: ReadyParams["tool_count"];
  warnings: ReadyParams["warnings"];
  models: ModelInfo[];
  modelCatalog?: ModelInfo[];
  loadedModels?: LoadedModelInfo[];
  loadedModelCount?: ReadyParams["loaded_model_count"];
  loadedModelMemoryBytes?: ReadyParams["loaded_model_memory_bytes"];
  sessionPath: ReadyParams["session_path"];
  focusFile?: ReadyParams["focus_file"];
  registryPath?: ReadyParams["registry_path"];
  broadcastModels?: ReadyParams["broadcast_models"];
  orchestratorModel?: ReadyParams["orchestrator_model"];
  sessionMessages?: ReadyParams["session_messages"];
  sessionToolCalls?: ReadyParams["session_tool_calls"];
  lastActiveAt?: ReadyParams["last_active_at"];
  lastActiveModel?: ReadyParams["last_active_model"];
  permissionRules?: ReadyParams["permission_rules"];
  verifyHooks?: ReadyParams["verify_hooks"];
  shellActive?: ReadyParams["shell_active"];
  shellCwd?: ReadyParams["shell_cwd"];
  cancelCount?: ReadyParams["cancel_count"];
  backendRestartCount?: ReadyParams["backend_restart_count"];
  toolLatencyMs?: ReadyParams["tool_latency_ms"];
  toolLatencySamples?: ReadyParams["tool_latency_samples"];
  reviewWaitMs?: ReadyParams["review_wait_ms"];
  permissionWaitMs?: ReadyParams["permission_wait_ms"];
  permissionTimeoutCount?: ReadyParams["permission_timeout_count"];
  reviewTimeoutCount?: ReadyParams["review_timeout_count"];
  modelRetryCount?: ReadyParams["model_retry_count"];
  modelRetryBackoffMs?: ReadyParams["model_retry_backoff_ms"];
  modelErrorCount?: ReadyParams["model_error_count"];
  toolTimeoutCount?: ReadyParams["tool_timeout_count"];
  modelBackpressureCount?: ReadyParams["model_backpressure_count"];
  toolBackpressureCount?: ReadyParams["tool_backpressure_count"];
  modelQueueHighwater?: ReadyParams["model_queue_highwater"];
  toolQueueHighwater?: ReadyParams["tool_queue_highwater"];
  modelInflightHighwater?: ReadyParams["model_inflight_highwater"];
  toolInflightHighwater?: ReadyParams["tool_inflight_highwater"];
  inflightModelCalls?: ReadyParams["inflight_model_calls"];
  queuedModelCalls?: ReadyParams["queued_model_calls"];
  inflightToolCalls?: ReadyParams["inflight_tool_calls"];
  queuedToolCalls?: ReadyParams["queued_tool_calls"];
  modelRetryMax?: ReadyParams["model_retry_max"];
  modelRetryBaseMs?: ReadyParams["model_retry_base_ms"];
  toolExecTimeoutS?: ReadyParams["tool_exec_timeout_s"];
  maxInflightModelCalls?: ReadyParams["max_inflight_model_calls"];
  maxInflightTools?: ReadyParams["max_inflight_tools"];
  execQueueDepth?: ReadyParams["exec_queue_depth"];
  requestCount?: ReadyParams["request_count"];
  requestSuccessCount?: ReadyParams["request_success_count"];
  requestErrorCount?: ReadyParams["request_error_count"];
  requestRejectCount?: ReadyParams["request_reject_count"];
  requestCancelCount?: ReadyParams["request_cancel_count"];
  spanCount?: ReadyParams["span_count"];
  lastRequestId?: ReadyParams["last_request_id"];
  lastSpanId?: ReadyParams["last_span_id"];
  lastToolCallId?: ReadyParams["last_tool_call_id"];
  requestSamples?: ReadyParams["request_samples"];
  queuedMsP50?: ReadyParams["queued_ms_p50"];
  queuedMsP95?: ReadyParams["queued_ms_p95"];
  modelMsP50?: ReadyParams["model_ms_p50"];
  modelMsP95?: ReadyParams["model_ms_p95"];
  toolMsP50?: ReadyParams["tool_ms_p50"];
  toolMsP95?: ReadyParams["tool_ms_p95"];
  totalMsP50?: ReadyParams["total_ms_p50"];
  totalMsP95?: ReadyParams["total_ms_p95"];
  lastRequestStatus?: ReadyParams["last_request_status"];
  lastRequestQueuedMs?: ReadyParams["last_request_queued_ms"];
  lastRequestModelMs?: ReadyParams["last_request_model_ms"];
  lastRequestToolMs?: ReadyParams["last_request_tool_ms"];
  lastRequestTotalMs?: ReadyParams["last_request_total_ms"];
}
