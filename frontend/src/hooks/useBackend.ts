/**
 * React hook for communicating with the z3cli Python backend.
 */

import { useState, useEffect, useCallback, useReducer, useRef } from "react";
import { Backend } from "../ipc/backend.js";
import type {
  AttachmentMeta,
  BackendEvent,
  AppConfig,
  ConstructRef,
  Message,
  ModelInfo,
} from "../ipc/protocol.js";
import {
  applySubagentEvent,
  pruneFinishedSubagents,
  type SubagentEntry,
  type SubagentEvent,
} from "../utils/subagentState.js";
import { cancelRequestTarget, evaluateRequestScope } from "../utils/requestScope.js";

interface BackendUIState {
  streamingContent: string;
  streamingThinking: string;
  isStreaming: boolean;
  activeToolCall: {
    name: string;
    server: string;
    elapsed: number;
  } | null;
  promptTokens: number;
  completionTokens: number;
  cacheCreationTokens: number;
  cacheReadTokens: number;
  error: string | null;
  pendingPermission: PendingPermission | null;
  pendingReview: PendingReview | null;
}

type BackendUIAction =
  | {
    type: "ready";
    promptTokens: number;
    completionTokens: number;
    cacheCreationTokens: number;
    cacheReadTokens: number;
  }
  | { type: "stream/start" }
  | { type: "stream/append_text"; delta: string }
  | { type: "stream/append_thinking"; delta: string }
  | { type: "stream/clear_text" }
  | { type: "stream/stop" }
  | { type: "tool_call/start"; name: string; server: string }
  | { type: "tool_call/tick"; elapsed: number }
  | { type: "tool_call/clear" }
  | { type: "tokens/add"; prompt: number; completion: number; cacheCreation: number; cacheRead: number }
  | { type: "error/set"; message: string | null }
  | { type: "permission/set"; permission: PendingPermission | null }
  | { type: "review/set"; review: PendingReview | null }
  | { type: "stream/error"; message: string }
  | { type: "stream/backend_exit"; message: string }
  | { type: "runtime/reset" };

const initialBackendUIState: BackendUIState = {
  streamingContent: "",
  streamingThinking: "",
  isStreaming: false,
  activeToolCall: null,
  promptTokens: 0,
  completionTokens: 0,
  cacheCreationTokens: 0,
  cacheReadTokens: 0,
  error: null,
  pendingPermission: null,
  pendingReview: null,
};

function backendUIReducer(state: BackendUIState, action: BackendUIAction): BackendUIState {
  switch (action.type) {
    case "ready":
      return {
        ...state,
        promptTokens: action.promptTokens,
        completionTokens: action.completionTokens,
        cacheCreationTokens: action.cacheCreationTokens,
        cacheReadTokens: action.cacheReadTokens,
      };
    case "stream/start":
      return {
        ...state,
        streamingContent: "",
        streamingThinking: "",
        isStreaming: true,
        error: null,
        pendingReview: null,
      };
    case "stream/append_text":
      return {
        ...state,
        streamingContent: state.streamingContent + action.delta,
      };
    case "stream/append_thinking":
      return {
        ...state,
        streamingThinking: state.streamingThinking + action.delta,
      };
    case "stream/clear_text":
      return {
        ...state,
        streamingContent: "",
      };
    case "stream/stop":
      return {
        ...state,
        streamingContent: "",
        streamingThinking: "",
        isStreaming: false,
        activeToolCall: null,
        pendingPermission: null,
        pendingReview: null,
      };
    case "tool_call/start":
      return {
        ...state,
        streamingContent: "",
        streamingThinking: "",
        activeToolCall: { name: action.name, server: action.server, elapsed: 0 },
      };
    case "tool_call/tick":
      return state.activeToolCall
        ? {
            ...state,
            activeToolCall: {
              ...state.activeToolCall,
              elapsed: action.elapsed,
            },
          }
        : state;
    case "tool_call/clear":
      return {
        ...state,
        activeToolCall: null,
      };
    case "tokens/add":
      return {
        ...state,
        promptTokens: state.promptTokens + action.prompt,
        completionTokens: state.completionTokens + action.completion,
        cacheCreationTokens: state.cacheCreationTokens + action.cacheCreation,
        cacheReadTokens: state.cacheReadTokens + action.cacheRead,
      };
    case "error/set":
      return {
        ...state,
        error: action.message,
      };
    case "permission/set":
      return {
        ...state,
        pendingPermission: action.permission,
      };
    case "review/set":
      return {
        ...state,
        pendingReview: action.review,
      };
    case "stream/error":
      return {
        ...state,
        streamingContent: "",
        streamingThinking: "",
        isStreaming: false,
        activeToolCall: null,
        error: action.message,
        pendingPermission: null,
        pendingReview: null,
      };
    case "stream/backend_exit":
      return {
        ...state,
        streamingContent: "",
        streamingThinking: "",
        isStreaming: false,
        activeToolCall: null,
        error: action.message,
        pendingPermission: null,
        pendingReview: null,
      };
    case "runtime/reset":
      return {
        ...state,
        streamingContent: "",
        streamingThinking: "",
        isStreaming: false,
        activeToolCall: null,
        error: null,
        pendingPermission: null,
        pendingReview: null,
      };
    default:
      return state;
  }
}

export interface LastCompaction {
  model: string;
  replaced: number;
  tokensBefore: number;
  tokensAfter: number;
  summary: string;
  timestamp: number;
}

let messageIdCounter = 0;
function nextMsgId(): string {
  return `msg-${++messageIdCounter}`;
}
/**
 * How often to flush buffered stream deltas to React state.
 * 33ms (~30fps) was triggering visible reflow flicker when text rewrapped on
 * append; 66ms (~15fps) halves the redraw cost and still feels live. Tokens
 * still accumulate in `streamBufferRef` between flushes, so nothing is lost.
 */
const STREAM_BATCH_MS = 66;

export interface PendingPermission {
  name: string;
  server: string;
  arguments: string;
  /**
   * Optional explanation from the backend for why this tool call is being
   * held for review (e.g. "denied by sticky rule", "write-access policy",
   * "subagent spawn from untrusted source"). Rendered in `PermissionDialog`.
   * Backend is expected to populate it; frontend falls back gracefully when
   * the field is absent.
   */
  reason?: string;
}

/**
 * Convert a raw `tool/permission_request` JSON-RPC params payload into the
 * shape the UI reducer consumes. Exported so the transformation can be
 * regression-tested without having to drive the full hook.
 */
export function parsePendingPermission(params: unknown): PendingPermission {
  const perm = params as {
    name: string;
    server: string;
    arguments: string;
    reason?: string;
  };
  return {
    name: perm.name,
    server: perm.server,
    arguments: perm.arguments,
    ...(perm.reason ? { reason: perm.reason } : {}),
  };
}

export interface PendingReview {
  reviewId: string;
  name: string;
  server: string;
  summary: string;
  paths: string[];
  diffLines: string[];
  omitted: number;
  verificationCommands: string[];
}

export interface UseBackendResult {
  config: AppConfig | null;
  messages: Message[];
  streamingContent: string;
  streamingThinking: string;
  isStreaming: boolean;
  activeToolCall: { name: string; server: string; elapsed: number } | null;
  promptTokens: number;
  completionTokens: number;
  cacheCreationTokens: number;
  cacheReadTokens: number;
  error: string | null;
  pendingPermission: PendingPermission | null;
  pendingReview: PendingReview | null;
  subagents: SubagentEntry[];
  lastCompaction: LastCompaction | null;
  clearFinishedSubagents: () => void;
  sendMessage: (text: string, attachments?: AttachmentMeta[], constructRefs?: ConstructRef[]) => Promise<void>;
  sendCommand: (cmd: string, args?: string[]) => Promise<unknown>;
  addSystemMessage: (content: string) => void;
  replaceMessages: (messages: Message[]) => void;
  replaceSubagents: (entries: SubagentEntry[]) => void;
  updateConfig: (patch: Partial<AppConfig>) => void;
  cancelStream: () => void;
  approveTool: () => Promise<void>;
  approveToolForSession: () => Promise<void>;
  denyTool: () => Promise<void>;
  denyToolForSession: () => Promise<void>;
  acceptToolReview: () => Promise<void>;
  rejectToolReview: () => Promise<void>;
  backend: Backend;
}

function normalizeBackendMessage(params: Record<string, unknown>): Message {
  const normalizeAttachment = (entry: unknown): AttachmentMeta | null => {
    if (!entry || typeof entry !== "object") return null;
    const maybeAttachment = entry as Record<string, unknown>;
    if (typeof maybeAttachment.path !== "string") {
      return null;
    }

    return {
      path: maybeAttachment.path,
      lines: typeof maybeAttachment.lines === "number" ? maybeAttachment.lines : 0,
      chars: typeof maybeAttachment.chars === "number" ? maybeAttachment.chars : 0,
    };
  };

  const normalizeConstructRef = (entry: unknown): ConstructRef | null => {
    if (!entry || typeof entry !== "object") return null;
    const maybeRef = entry as Record<string, unknown>;
    if (typeof maybeRef.kind !== "string" || typeof maybeRef.query !== "string") {
      return null;
    }

    return {
      kind: maybeRef.kind,
      query: maybeRef.query,
      ...(typeof maybeRef.token === "string" ? { token: maybeRef.token } : {}),
      ...(typeof maybeRef.id === "string" ? { id: maybeRef.id } : {}),
      ...(typeof maybeRef.label === "string" ? { label: maybeRef.label } : {}),
    };
  };

  return {
    id: typeof params.id === "string" ? params.id : nextMsgId(),
    role: params.role as Message["role"],
    content: typeof params.content === "string" ? params.content : "",
    thinking:
      typeof params.thinking === "string" && params.thinking ? params.thinking : undefined,
    model: typeof params.model === "string" && params.model ? params.model : undefined,
    toolName:
      typeof params.tool_name === "string" && params.tool_name ? params.tool_name : undefined,
    toolServer:
      typeof params.tool_server === "string" && params.tool_server ? params.tool_server : undefined,
    toolArguments:
      typeof params.tool_arguments === "string" ? params.tool_arguments : undefined,
    timestamp: typeof params.timestamp === "number" ? params.timestamp : Date.now(),
    turnId:
      typeof params.turn_id === "string" && params.turn_id ? params.turn_id : undefined,
    toolGroup:
      typeof params.tool_group === "string" && params.tool_group ? params.tool_group : undefined,
    requestId:
      typeof params.request_id === "string" && params.request_id ? params.request_id : undefined,
    spanId:
      typeof params.span_id === "string" && params.span_id ? params.span_id : undefined,
    attachments: Array.isArray(params.attachments)
      ? params.attachments
        .map(normalizeAttachment)
        .flatMap((item) => (item ? [item] : []))
      : undefined,
    constructRefs: Array.isArray(params.construct_refs)
      ? params.construct_refs
        .map(normalizeConstructRef)
        .flatMap((item) => (item ? [item] : []))
      : undefined,
  };
}

function permissionRuleKey(permission: PendingPermission | null): string | null {
  if (!permission) return null;
  return permission.server ? `${permission.server}:${permission.name}` : permission.name;
}

export function useBackend(pythonPath: string, args: string[] = []): UseBackendResult {
  const backendRef = useRef<Backend | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [uiState, dispatchUI] = useReducer(backendUIReducer, initialBackendUIState);
  const {
    streamingContent,
    streamingThinking,
    isStreaming,
    activeToolCall,
    promptTokens,
    completionTokens,
    cacheCreationTokens,
    cacheReadTokens,
    error,
    pendingPermission,
    pendingReview,
  } = uiState;
  const [subagents, setSubagents] = useState<SubagentEntry[]>([]);
  const [lastCompaction, setLastCompaction] = useState<LastCompaction | null>(null);

  const toolTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const toolStartRef = useRef<number>(0);
  const cancelledRef = useRef(false);
  const activeRequestIdRef = useRef("");
  const chatCompletionRef = useRef<{
    resolve: () => void;
    reject: (error: Error) => void;
  } | null>(null);
  const streamBufferRef = useRef<{ text: string; thinking: string }>({ text: "", thinking: "" });
  const streamFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelPendingStreamFlush = useCallback(() => {
    if (streamFlushTimerRef.current) {
      clearTimeout(streamFlushTimerRef.current);
      streamFlushTimerRef.current = null;
    }
    streamBufferRef.current.text = "";
    streamBufferRef.current.thinking = "";
  }, []);

  const flushStreamBuffers = useCallback(() => {
    if (streamFlushTimerRef.current) {
      clearTimeout(streamFlushTimerRef.current);
      streamFlushTimerRef.current = null;
    }
    const text = streamBufferRef.current.text;
    const thinking = streamBufferRef.current.thinking;
    streamBufferRef.current.text = "";
    streamBufferRef.current.thinking = "";
    if (thinking) {
      dispatchUI({ type: "stream/append_thinking", delta: thinking });
    }
    if (text) {
      dispatchUI({ type: "stream/append_text", delta: text });
    }
  }, []);

  const queueStreamDelta = useCallback((kind: "text" | "thinking", delta: string) => {
    if (!delta) return;
    if (kind === "thinking") {
      streamBufferRef.current.thinking += delta;
    } else {
      streamBufferRef.current.text += delta;
    }
    if (!streamFlushTimerRef.current) {
      streamFlushTimerRef.current = setTimeout(() => {
        flushStreamBuffers();
      }, STREAM_BATCH_MS);
    }
  }, [flushStreamBuffers]);

  const stopToolElapsedTimer = useCallback(() => {
    if (toolTimerRef.current) {
      clearInterval(toolTimerRef.current);
      toolTimerRef.current = null;
    }
  }, []);

  const clearToolCallState = useCallback(() => {
    stopToolElapsedTimer();
    dispatchUI({ type: "tool_call/clear" });
  }, [stopToolElapsedTimer]);

  const resetStreamingState = useCallback(() => {
    flushStreamBuffers();
    cancelPendingStreamFlush();
    stopToolElapsedTimer();
    dispatchUI({ type: "stream/stop" });
  }, [cancelPendingStreamFlush, flushStreamBuffers, stopToolElapsedTimer]);

  const resolveActiveChat = useCallback(() => {
    const pending = chatCompletionRef.current;
    if (!pending) {
      return;
    }
    chatCompletionRef.current = null;
    activeRequestIdRef.current = "";
    pending.resolve();
  }, []);

  const rejectActiveChat = useCallback((message: string) => {
    const pending = chatCompletionRef.current;
    if (!pending) {
      return;
    }
    chatCompletionRef.current = null;
    activeRequestIdRef.current = "";
    pending.reject(new Error(message));
  }, []);

  const shouldProcessRequestScopedEvent = useCallback((requestIdValue: unknown): boolean => {
    const decision = evaluateRequestScope(activeRequestIdRef.current, requestIdValue);
    activeRequestIdRef.current = decision.nextActiveRequestId;
    return decision.accept;
  }, []);

  useEffect(() => {
    const backend = new Backend(pythonPath, args);
    backendRef.current = backend;
    let disposed = false;

    backend.on("event", (event: BackendEvent) => {
      if (disposed) return;
      switch (event.method) {
        case "ready": {
          const p = event.params!;
          dispatchUI({
            type: "ready",
            promptTokens: typeof p.prompt_tokens === "number" ? p.prompt_tokens : 0,
            completionTokens: typeof p.completion_tokens === "number" ? p.completion_tokens : 0,
            cacheCreationTokens:
              typeof p.cache_creation_tokens === "number" ? p.cache_creation_tokens : 0,
            cacheReadTokens:
              typeof p.cache_read_tokens === "number" ? p.cache_read_tokens : 0,
          });
          setConfig({
            version: p.version as string,
            backend: p.backend as string,
            activeModel: p.active_model as string,
            studioModel: p.studio_model as string | undefined,
            mode: p.mode as string,
            workspace: p.workspace as string,
            romPath: p.rom_path as string,
            toolsEnabled: p.tools_enabled as boolean,
            toolsWrite: p.tools_write as boolean | undefined,
            servers: p.servers as string[],
            toolCount: p.tool_count as number,
            warnings: (p.warnings as string[] | undefined) ?? [],
            sessionPath: (p.session_path as string) ?? "",
            focusFile:
              typeof p.focus_file === "string" && p.focus_file
                ? p.focus_file
                : undefined,
            registryPath:
              typeof p.registry_path === "string" && p.registry_path
                ? p.registry_path
                : undefined,
            broadcastModels: (p.broadcast_models as string[] | undefined) ?? [],
            orchestratorModel:
              typeof p.orchestrator_model === "string" ? p.orchestrator_model : undefined,
            models: Array.isArray(p.models)
              ? p.models.map(
                  (m): ModelInfo => ({
                    name: m.name,
                    modelId: m.model_id,
                    role: m.role,
                    description: typeof m.description === "string" ? m.description : undefined,
                    loaded: m.loaded,
                    selectable: typeof m.selectable === "boolean" ? m.selectable : undefined,
                    toolsEnabled: m.tools_enabled,
                    provider: typeof m.provider === "string" ? m.provider : undefined,
                    contextBudget:
                      typeof m.context_budget === "number" ? m.context_budget : undefined,
                    loadedIdentifier:
                      typeof m.loaded_identifier === "string" ? m.loaded_identifier : undefined,
                    sizeBytes:
                      typeof m.size_bytes === "number" ? m.size_bytes : undefined,
                    status:
                      typeof m.status === "string" ? m.status : undefined,
                    parallel:
                      typeof m.parallel === "number" ? m.parallel : undefined,
                    contextLength:
                      typeof m.context_length === "number" ? m.context_length : undefined,
                    maxContextLength:
                      typeof m.max_context_length === "number" ? m.max_context_length : undefined,
                    architecture:
                      typeof m.architecture === "string" ? m.architecture : undefined,
                    quantization:
                      typeof m.quantization === "string" ? m.quantization : undefined,
                    queued:
                      typeof m.queued === "number" ? m.queued : undefined,
                    estimatedGpuBytes:
                      typeof m.estimated_gpu_bytes === "number" ? m.estimated_gpu_bytes : undefined,
                    estimatedTotalBytes:
                      typeof m.estimated_total_bytes === "number" ? m.estimated_total_bytes : undefined,
                  }),
                )
              : [],
            modelCatalog: Array.isArray(p.model_catalog)
              ? p.model_catalog.map(
                  (m): ModelInfo => ({
                    name: m.name,
                    modelId: m.model_id,
                    role: m.role,
                    description: typeof m.description === "string" ? m.description : undefined,
                    loaded: m.loaded,
                    selectable: typeof m.selectable === "boolean" ? m.selectable : undefined,
                    toolsEnabled: m.tools_enabled,
                    provider: typeof m.provider === "string" ? m.provider : undefined,
                    contextBudget:
                      typeof m.context_budget === "number" ? m.context_budget : undefined,
                    loadedIdentifier:
                      typeof m.loaded_identifier === "string" ? m.loaded_identifier : undefined,
                    sizeBytes:
                      typeof m.size_bytes === "number" ? m.size_bytes : undefined,
                    status:
                      typeof m.status === "string" ? m.status : undefined,
                    parallel:
                      typeof m.parallel === "number" ? m.parallel : undefined,
                    contextLength:
                      typeof m.context_length === "number" ? m.context_length : undefined,
                    maxContextLength:
                      typeof m.max_context_length === "number" ? m.max_context_length : undefined,
                    architecture:
                      typeof m.architecture === "string" ? m.architecture : undefined,
                    quantization:
                      typeof m.quantization === "string" ? m.quantization : undefined,
                    queued:
                      typeof m.queued === "number" ? m.queued : undefined,
                    estimatedGpuBytes:
                      typeof m.estimated_gpu_bytes === "number" ? m.estimated_gpu_bytes : undefined,
                    estimatedTotalBytes:
                      typeof m.estimated_total_bytes === "number" ? m.estimated_total_bytes : undefined,
                  }),
                )
              : undefined,
            loadedModels: Array.isArray(p.loaded_models)
              ? p.loaded_models.flatMap((entry) => {
                  if (!entry || typeof entry !== "object") return [];
                  const candidate = entry as unknown as Record<string, unknown>;
                  if (typeof candidate.identifier !== "string" || typeof candidate.model_key !== "string") {
                    return [];
                  }
                  return [{
                    identifier: candidate.identifier,
                    modelKey: candidate.model_key,
                    ...(typeof candidate.display_name === "string" ? { displayName: candidate.display_name } : {}),
                    ...(typeof candidate.size_bytes === "number" ? { sizeBytes: candidate.size_bytes } : {}),
                    ...(typeof candidate.architecture === "string" ? { architecture: candidate.architecture } : {}),
                    ...(typeof candidate.quantization === "string" ? { quantization: candidate.quantization } : {}),
                    ...(typeof candidate.context_length === "number" ? { contextLength: candidate.context_length } : {}),
                    ...(typeof candidate.max_context_length === "number" ? { maxContextLength: candidate.max_context_length } : {}),
                    ...(typeof candidate.parallel === "number" ? { parallel: candidate.parallel } : {}),
                    ...(typeof candidate.status === "string" ? { status: candidate.status } : {}),
                    ...(typeof candidate.queued === "number" ? { queued: candidate.queued } : {}),
                    ...(typeof candidate.ttl_ms === "number" ? { ttlMs: candidate.ttl_ms } : {}),
                    ...(typeof candidate.estimated_gpu_bytes === "number" ? { estimatedGpuBytes: candidate.estimated_gpu_bytes } : {}),
                    ...(typeof candidate.estimated_total_bytes === "number" ? { estimatedTotalBytes: candidate.estimated_total_bytes } : {}),
                  }];
                })
              : undefined,
            loadedModelCount:
              typeof p.loaded_model_count === "number" ? p.loaded_model_count : undefined,
            loadedModelMemoryBytes:
              typeof p.loaded_model_memory_bytes === "number" ? p.loaded_model_memory_bytes : undefined,
            sessionMessages:
              typeof p.session_messages === "number" ? p.session_messages : undefined,
            sessionToolCalls:
              typeof p.session_tool_calls === "number" ? p.session_tool_calls : undefined,
            lastActiveAt:
              typeof p.last_active_at === "string" ? p.last_active_at : undefined,
            lastActiveModel:
              typeof p.last_active_model === "string" ? p.last_active_model : undefined,
            permissionRules:
              typeof p.permission_rules === "object" && p.permission_rules
                ? (p.permission_rules as Record<string, boolean>)
                : undefined,
            verifyHooks: typeof p.verify_hooks === "boolean" ? p.verify_hooks : undefined,
            shellActive: typeof p.shell_active === "boolean" ? p.shell_active : undefined,
            shellCwd: typeof p.shell_cwd === "string" ? p.shell_cwd : undefined,
            cancelCount: typeof p.cancel_count === "number" ? p.cancel_count : undefined,
            backendRestartCount:
              typeof p.backend_restart_count === "number" ? p.backend_restart_count : undefined,
            toolLatencyMs: typeof p.tool_latency_ms === "number" ? p.tool_latency_ms : undefined,
            toolLatencySamples:
              typeof p.tool_latency_samples === "number" ? p.tool_latency_samples : undefined,
            reviewWaitMs: typeof p.review_wait_ms === "number" ? p.review_wait_ms : undefined,
            permissionWaitMs:
              typeof p.permission_wait_ms === "number" ? p.permission_wait_ms : undefined,
            permissionTimeoutCount:
              typeof p.permission_timeout_count === "number" ? p.permission_timeout_count : undefined,
            reviewTimeoutCount:
              typeof p.review_timeout_count === "number" ? p.review_timeout_count : undefined,
            modelRetryCount:
              typeof p.model_retry_count === "number" ? p.model_retry_count : undefined,
            modelRetryBackoffMs:
              typeof p.model_retry_backoff_ms === "number" ? p.model_retry_backoff_ms : undefined,
            modelErrorCount:
              typeof p.model_error_count === "number" ? p.model_error_count : undefined,
            toolTimeoutCount:
              typeof p.tool_timeout_count === "number" ? p.tool_timeout_count : undefined,
            modelBackpressureCount:
              typeof p.model_backpressure_count === "number" ? p.model_backpressure_count : undefined,
            toolBackpressureCount:
              typeof p.tool_backpressure_count === "number" ? p.tool_backpressure_count : undefined,
            modelQueueHighwater:
              typeof p.model_queue_highwater === "number" ? p.model_queue_highwater : undefined,
            toolQueueHighwater:
              typeof p.tool_queue_highwater === "number" ? p.tool_queue_highwater : undefined,
            modelInflightHighwater:
              typeof p.model_inflight_highwater === "number" ? p.model_inflight_highwater : undefined,
            toolInflightHighwater:
              typeof p.tool_inflight_highwater === "number" ? p.tool_inflight_highwater : undefined,
            inflightModelCalls:
              typeof p.inflight_model_calls === "number" ? p.inflight_model_calls : undefined,
            queuedModelCalls:
              typeof p.queued_model_calls === "number" ? p.queued_model_calls : undefined,
            inflightToolCalls:
              typeof p.inflight_tool_calls === "number" ? p.inflight_tool_calls : undefined,
            queuedToolCalls:
              typeof p.queued_tool_calls === "number" ? p.queued_tool_calls : undefined,
            modelRetryMax:
              typeof p.model_retry_max === "number" ? p.model_retry_max : undefined,
            modelRetryBaseMs:
              typeof p.model_retry_base_ms === "number" ? p.model_retry_base_ms : undefined,
            toolExecTimeoutS:
              typeof p.tool_exec_timeout_s === "number" ? p.tool_exec_timeout_s : undefined,
            maxInflightModelCalls:
              typeof p.max_inflight_model_calls === "number" ? p.max_inflight_model_calls : undefined,
            maxInflightTools:
              typeof p.max_inflight_tools === "number" ? p.max_inflight_tools : undefined,
            execQueueDepth:
              typeof p.exec_queue_depth === "number" ? p.exec_queue_depth : undefined,
            requestCount:
              typeof p.request_count === "number" ? p.request_count : undefined,
            requestSuccessCount:
              typeof p.request_success_count === "number" ? p.request_success_count : undefined,
            requestErrorCount:
              typeof p.request_error_count === "number" ? p.request_error_count : undefined,
            requestRejectCount:
              typeof p.request_reject_count === "number" ? p.request_reject_count : undefined,
            requestCancelCount:
              typeof p.request_cancel_count === "number" ? p.request_cancel_count : undefined,
            spanCount:
              typeof p.span_count === "number" ? p.span_count : undefined,
            lastRequestId:
              typeof p.last_request_id === "string" ? p.last_request_id : undefined,
            lastSpanId:
              typeof p.last_span_id === "string" ? p.last_span_id : undefined,
            lastToolCallId:
              typeof p.last_tool_call_id === "string" ? p.last_tool_call_id : undefined,
            requestSamples:
              typeof p.request_samples === "number" ? p.request_samples : undefined,
            queuedMsP50:
              typeof p.queued_ms_p50 === "number" ? p.queued_ms_p50 : undefined,
            queuedMsP95:
              typeof p.queued_ms_p95 === "number" ? p.queued_ms_p95 : undefined,
            modelMsP50:
              typeof p.model_ms_p50 === "number" ? p.model_ms_p50 : undefined,
            modelMsP95:
              typeof p.model_ms_p95 === "number" ? p.model_ms_p95 : undefined,
            toolMsP50:
              typeof p.tool_ms_p50 === "number" ? p.tool_ms_p50 : undefined,
            toolMsP95:
              typeof p.tool_ms_p95 === "number" ? p.tool_ms_p95 : undefined,
            totalMsP50:
              typeof p.total_ms_p50 === "number" ? p.total_ms_p50 : undefined,
            totalMsP95:
              typeof p.total_ms_p95 === "number" ? p.total_ms_p95 : undefined,
            lastRequestStatus:
              typeof p.last_request_status === "string" ? p.last_request_status : undefined,
            lastRequestQueuedMs:
              typeof p.last_request_queued_ms === "number" ? p.last_request_queued_ms : undefined,
            lastRequestModelMs:
              typeof p.last_request_model_ms === "number" ? p.last_request_model_ms : undefined,
            lastRequestToolMs:
              typeof p.last_request_tool_ms === "number" ? p.last_request_tool_ms : undefined,
            lastRequestTotalMs:
              typeof p.last_request_total_ms === "number" ? p.last_request_total_ms : undefined,
          });
          break;
        }
        case "message": {
          if (!shouldProcessRequestScopedEvent((event.params as { request_id?: unknown } | null)?.request_id)) {
            break;
          }
          const message = normalizeBackendMessage(
            ((event.params ?? {}) as unknown) as Record<string, unknown>,
          );
          if (message.role === "assistant") {
            flushStreamBuffers();
            cancelPendingStreamFlush();
            dispatchUI({ type: "stream/clear_text" });
          }
          setMessages((msgs) => [...msgs, message]);
          break;
        }
        case "thinking":
          if (!cancelledRef.current) {
            const payload = event.params as { delta: string; request_id?: string };
            if (shouldProcessRequestScopedEvent(payload.request_id)) {
              queueStreamDelta("thinking", payload.delta);
            }
          }
          break;
        case "text":
          if (!cancelledRef.current) {
            const payload = event.params as { delta: string; request_id?: string };
            if (shouldProcessRequestScopedEvent(payload.request_id)) {
              queueStreamDelta("text", payload.delta);
            }
          }
          break;

        case "tool_call": {
          flushStreamBuffers();
          cancelPendingStreamFlush();
          const tc = event.params as { name: string; server: string; arguments: string; request_id?: string };
          if (!shouldProcessRequestScopedEvent(tc.request_id)) {
            break;
          }
          toolStartRef.current = Date.now();
          dispatchUI({ type: "tool_call/start", name: tc.name, server: tc.server });
          stopToolElapsedTimer();
          toolTimerRef.current = setInterval(() => {
            dispatchUI({
              type: "tool_call/tick",
              elapsed: Math.floor((Date.now() - toolStartRef.current) / 1000),
            });
          }, 1000);
          break;
        }

        case "tool_result": {
          const payload = event.params as { request_id?: string };
          if (!shouldProcessRequestScopedEvent(payload.request_id)) {
            break;
          }
          clearToolCallState();
          break;
        }

        case "tool/review_request": {
          clearToolCallState();
          const review = event.params as {
            review_id: string;
            name: string;
            server: string;
            summary: string;
            paths: string[];
            diff_lines: string[];
            omitted: number;
            verification_commands?: string[];
          };
          dispatchUI({
            type: "review/set",
            review: {
              reviewId: review.review_id,
              name: review.name,
              server: review.server,
              summary: review.summary,
              paths: Array.isArray(review.paths) ? review.paths : [],
              diffLines: Array.isArray(review.diff_lines) ? review.diff_lines : [],
              omitted: typeof review.omitted === "number" ? review.omitted : 0,
              verificationCommands: Array.isArray(review.verification_commands)
                ? review.verification_commands.filter((item): item is string => typeof item === "string")
                : [],
            },
          });
          break;
        }

        case "done": {
          flushStreamBuffers();
          cancelPendingStreamFlush();
          const done = event.params as {
            prompt_tokens: number;
            completion_tokens: number;
            cache_creation_tokens?: number;
            cache_read_tokens?: number;
            request_id?: string;
          };
          if (!shouldProcessRequestScopedEvent(done.request_id)) {
            break;
          }
          const prompt = Number.isFinite(done.prompt_tokens) ? done.prompt_tokens : 0;
          const completion = Number.isFinite(done.completion_tokens) ? done.completion_tokens : 0;
          dispatchUI({
            type: "tokens/add",
            prompt,
            completion,
            cacheCreation: typeof done.cache_creation_tokens === "number" ? done.cache_creation_tokens : 0,
            cacheRead: typeof done.cache_read_tokens === "number" ? done.cache_read_tokens : 0,
          });
          cancelledRef.current = false;
          resetStreamingState();
          resolveActiveChat();
          break;
        }

        case "tool/permission_request": {
          dispatchUI({
            type: "permission/set",
            permission: parsePendingPermission(event.params),
          });
          break;
        }

        case "error":
          {
            const payload = event.params as { message: string; request_id?: string };
            if (!shouldProcessRequestScopedEvent(payload.request_id)) {
              break;
            }
            cancelledRef.current = false;
            cancelPendingStreamFlush();
            stopToolElapsedTimer();
            dispatchUI({ type: "stream/error", message: payload.message });
            rejectActiveChat(payload.message);
          }
          break;

        case "subagent/start": {
          const p = event.params as {
            id: string;
            name: string;
            model: string;
            provider: string;
            depth?: number;
            parent_id?: string | null;
          };
          setSubagents((prev) =>
            applySubagentEvent(prev, {
              kind: "start",
              id: p.id,
              name: p.name,
              model: p.model,
              provider: p.provider,
              depth: typeof p.depth === "number" ? p.depth : 0,
              parentId: typeof p.parent_id === "string" && p.parent_id ? p.parent_id : undefined,
            } as SubagentEvent),
          );
          break;
        }

        case "subagent/text": {
          const p = event.params as { id: string; delta: string };
          setSubagents((prev) =>
            applySubagentEvent(prev, { kind: "text", id: p.id, delta: p.delta }),
          );
          break;
        }

        case "subagent/thinking": {
          const p = event.params as { id: string; delta: string };
          setSubagents((prev) =>
            applySubagentEvent(prev, { kind: "thinking", id: p.id, delta: p.delta }),
          );
          break;
        }

        case "subagent/tool_call": {
          const p = event.params as { id: string; name: string; server: string };
          setSubagents((prev) =>
            applySubagentEvent(prev, {
              kind: "tool_call",
              id: p.id,
              name: p.name,
              server: p.server,
            }),
          );
          break;
        }

        case "subagent/tool_result": {
          const p = event.params as { id: string };
          setSubagents((prev) =>
            applySubagentEvent(prev, { kind: "tool_result", id: p.id }),
          );
          break;
        }

        case "subagent/done": {
          const p = event.params as {
            id: string;
            name: string;
            model: string;
            text: string;
            prompt_tokens: number;
            completion_tokens: number;
            tool_calls: number;
            error?: string;
            cancelled?: boolean;
          };
          setSubagents((prev) =>
            applySubagentEvent(prev, {
              kind: "done",
              id: p.id,
              name: p.name,
              model: p.model,
              text: p.text,
              promptTokens: p.prompt_tokens,
              completionTokens: p.completion_tokens,
              toolCalls: p.tool_calls,
              error: p.error,
              cancelled: p.cancelled,
            }),
          );
          break;
        }

        case "subagent/error": {
          const p = event.params as { id: string; message: string };
          setSubagents((prev) =>
            applySubagentEvent(prev, { kind: "error", id: p.id, message: p.message }),
          );
          break;
        }

        case "context/compacted": {
          const p = event.params as {
            model: string;
            replaced: number;
            tokens_before: number;
            tokens_after: number;
            summary: string;
          };
          setLastCompaction({
            model: p.model,
            replaced: p.replaced,
            tokensBefore: p.tokens_before,
            tokensAfter: p.tokens_after,
            summary: p.summary,
            timestamp: Date.now(),
          });
          break;
        }
      }
    });

    backend.on("exit", (code: number) => {
      if (disposed) return;
      const message = code === 0 ? "Backend exited" : `Backend exited with code ${code}`;
      cancelledRef.current = false;
      cancelPendingStreamFlush();
      stopToolElapsedTimer();
      dispatchUI({ type: "stream/backend_exit", message });
      rejectActiveChat(message);
    });

    backend.start();

    return () => {
      disposed = true;
      backend.stop();
      cancelPendingStreamFlush();
      stopToolElapsedTimer();
      rejectActiveChat("Backend stopped");
    };
  }, [
    args,
    cancelPendingStreamFlush,
    clearToolCallState,
    pythonPath,
    rejectActiveChat,
    resetStreamingState,
    resolveActiveChat,
    queueStreamDelta,
    flushStreamBuffers,
    stopToolElapsedTimer,
    shouldProcessRequestScopedEvent,
  ]);

  const cancelStream = useCallback(() => {
    if (!backendRef.current?.running) return;
    cancelledRef.current = true;
    cancelPendingStreamFlush();
    backendRef.current.cancel(cancelRequestTarget(activeRequestIdRef.current));
    clearToolCallState();
  }, [cancelPendingStreamFlush, clearToolCallState]);

  const sendMessage = useCallback(
    async (
      text: string,
      attachments: AttachmentMeta[] = [],
      constructRefs: ConstructRef[] = [],
    ) => {
      if (!backendRef.current?.running) return;
      if (chatCompletionRef.current) {
        throw new Error("Already streaming a chat response");
      }
      cancelledRef.current = false;
      activeRequestIdRef.current = "";
      cancelPendingStreamFlush();
      dispatchUI({ type: "stream/start" });
      setSubagents((prev) => pruneFinishedSubagents(prev));
      await new Promise<void>((resolve, reject) => {
        chatCompletionRef.current = { resolve, reject };
        backendRef.current?.chat(text, undefined, attachments, constructRefs).then((requestId) => {
          if (requestId) {
            activeRequestIdRef.current = requestId;
          }
        }).catch((e) => {
          resetStreamingState();
          const message = e instanceof Error ? e.message : String(e);
          dispatchUI({ type: "error/set", message });
          rejectActiveChat(message);
        });
      });
    },
    [rejectActiveChat, resetStreamingState],
  );

  const sendCommand = useCallback(
    async (cmd: string, args: string[] = []): Promise<unknown> => {
      if (!backendRef.current?.running) throw new Error("Backend not running");
      return backendRef.current.command(cmd, args);
    },
    [],
  );

  const addSystemMessage = useCallback((content: string) => {
    setMessages((msgs) => [
      ...msgs,
      { id: nextMsgId(), role: "system", content, timestamp: Date.now() },
    ]);
  }, []);

  const replaceMessages = useCallback((nextMessages: Message[]) => {
    cancelledRef.current = false;
    activeRequestIdRef.current = "";
    chatCompletionRef.current = null;
    cancelPendingStreamFlush();
    stopToolElapsedTimer();
    dispatchUI({ type: "runtime/reset" });
    setSubagents([]);
    setMessages(nextMessages);
  }, [cancelPendingStreamFlush, stopToolElapsedTimer]);

  const replaceSubagents = useCallback((entries: SubagentEntry[]) => {
    setSubagents(entries);
  }, []);

  const updateConfig = useCallback((patch: Partial<AppConfig>) => {
    setConfig((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  const approveTool = useCallback(async () => {
    if (!backendRef.current?.running) return;
    dispatchUI({ type: "permission/set", permission: null });
    await backendRef.current.command("tool/decision", ["allow-once"]);
  }, []);

  const approveToolForSession = useCallback(async () => {
    if (!backendRef.current?.running) return;
    const ruleKey = permissionRuleKey(pendingPermission);
    dispatchUI({ type: "permission/set", permission: null });
    await backendRef.current.command("tool/decision", ["allow-session"]);
    if (ruleKey) {
      setConfig((prev) =>
        prev
          ? {
              ...prev,
              permissionRules: { ...(prev.permissionRules ?? {}), [ruleKey]: true },
            }
          : prev,
      );
    }
  }, [pendingPermission]);

  const denyTool = useCallback(async () => {
    if (!backendRef.current?.running) return;
    dispatchUI({ type: "permission/set", permission: null });
    await backendRef.current.command("tool/decision", ["deny-once"]);
  }, []);

  const denyToolForSession = useCallback(async () => {
    if (!backendRef.current?.running) return;
    const ruleKey = permissionRuleKey(pendingPermission);
    dispatchUI({ type: "permission/set", permission: null });
    await backendRef.current.command("tool/decision", ["deny-session"]);
    if (ruleKey) {
      setConfig((prev) =>
        prev
          ? {
              ...prev,
              permissionRules: { ...(prev.permissionRules ?? {}), [ruleKey]: false },
            }
          : prev,
      );
    }
  }, [pendingPermission]);

  const acceptToolReview = useCallback(async () => {
    if (!backendRef.current?.running || !pendingReview) return;
    const reviewId = pendingReview.reviewId;
    dispatchUI({ type: "review/set", review: null });
    await backendRef.current.command("tool/review", [reviewId, "accept"]);
  }, [pendingReview]);

  const rejectToolReview = useCallback(async () => {
    if (!backendRef.current?.running || !pendingReview) return;
    const reviewId = pendingReview.reviewId;
    dispatchUI({ type: "review/set", review: null });
    await backendRef.current.command("tool/review", [reviewId, "reject"]);
  }, [pendingReview]);

  const clearFinishedSubagents = useCallback(() => {
    setSubagents((prev) => pruneFinishedSubagents(prev));
  }, []);

  return {
    config,
    messages,
    streamingContent,
    streamingThinking,
    isStreaming,
    activeToolCall,
    promptTokens,
    completionTokens,
    cacheCreationTokens,
    cacheReadTokens,
    error,
    pendingPermission,
    pendingReview,
    subagents,
    lastCompaction,
    clearFinishedSubagents,
    sendMessage,
    sendCommand,
    addSystemMessage,
    replaceMessages,
    replaceSubagents,
    updateConfig,
    cancelStream,
    approveTool,
    approveToolForSession,
    denyTool,
    denyToolForSession,
    acceptToolReview,
    rejectToolReview,
    backend: backendRef.current!,
  };
}
