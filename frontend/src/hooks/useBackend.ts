/**
 * React hook for communicating with the z3cli Python backend.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { Backend } from "../ipc/backend.js";
import type { BackendEvent, AppConfig, Message, ModelInfo } from "../ipc/protocol.js";

let messageIdCounter = 0;
function nextMsgId(): string {
  return `msg-${++messageIdCounter}`;
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
  error: string | null;
  sendMessage: (text: string) => Promise<void>;
  sendCommand: (cmd: string, args?: string[]) => Promise<unknown>;
  addSystemMessage: (content: string) => void;
  updateConfig: (patch: Partial<AppConfig>) => void;
  cancelStream: () => void;
  backend: Backend;
}

export function useBackend(pythonPath: string, args: string[] = []): UseBackendResult {
  const backendRef = useRef<Backend | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [streamingThinking, setStreamingThinking] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeToolCall, setActiveToolCall] = useState<{
    name: string;
    server: string;
    elapsed: number;
  } | null>(null);
  const [promptTokens, setPromptTokens] = useState(0);
  const [completionTokens, setCompletionTokens] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const toolTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const toolStartRef = useRef<number>(0);
  const cancelledRef = useRef(false);
  const chatCompletionRef = useRef<{
    resolve: () => void;
    reject: (error: Error) => void;
  } | null>(null);

  const clearToolCallState = useCallback(() => {
    setActiveToolCall(null);
    if (toolTimerRef.current) {
      clearInterval(toolTimerRef.current);
      toolTimerRef.current = null;
    }
  }, []);

  const resolveActiveChat = useCallback(() => {
    const pending = chatCompletionRef.current;
    if (!pending) {
      return;
    }
    chatCompletionRef.current = null;
    pending.resolve();
  }, []);

  const rejectActiveChat = useCallback((message: string) => {
    const pending = chatCompletionRef.current;
    if (!pending) {
      return;
    }
    chatCompletionRef.current = null;
    pending.reject(new Error(message));
  }, []);

  useEffect(() => {
    const backend = new Backend(pythonPath, args);
    backendRef.current = backend;

    backend.on("event", (event: BackendEvent) => {
      switch (event.method) {
        case "ready": {
          const p = event.params!;
          setConfig({
            version: p.version as string,
            backend: p.backend as string,
            activeModel: p.active_model as string,
            studioModel: p.studio_model as string | undefined,
            mode: p.mode as string,
            workspace: p.workspace as string,
            romPath: p.rom_path as string,
            toolsEnabled: p.tools_enabled as boolean,
            servers: p.servers as string[],
            toolCount: p.tool_count as number,
            warnings: (p.warnings as string[] | undefined) ?? [],
            sessionPath: (p.session_path as string) ?? "",
            focusFile: (p.focus_file as string | undefined) ?? undefined,
            broadcastModels: (p.broadcast_models as string[] | undefined) ?? [],
            models: (p.models as Array<Record<string, unknown>>).map(
              (m): ModelInfo => ({
                name: m.name as string,
                modelId: m.model_id as string,
                role: m.role as string,
                loaded: m.loaded as boolean,
                toolsEnabled: m.tools_enabled as boolean,
              }),
            ),
          });
          break;
        }
        case "thinking":
          if (!cancelledRef.current) {
            setStreamingThinking((prev) => prev + ((event.params as { delta: string }).delta));
          }
          break;
        case "text":
          if (!cancelledRef.current) {
            setStreamingContent((prev) => prev + ((event.params as { delta: string }).delta));
          }
          break;

        case "tool_call": {
          setStreamingContent((prev) => {
            if (prev.trim()) {
              setMessages((msgs) => [
                ...msgs,
                {
                  id: nextMsgId(),
                  role: "assistant",
                  content: prev,
                  timestamp: Date.now(),
                },
              ]);
            }
            return "";
          });
          const tc = event.params as { name: string; server: string; arguments: string };
          setMessages((msgs) => [
            ...msgs,
            {
              id: nextMsgId(),
              role: "tool",
              content: "",
              toolName: tc.name,
              toolServer: tc.server,
              toolArguments: tc.arguments,
              timestamp: Date.now(),
            },
          ]);
          toolStartRef.current = Date.now();
          setActiveToolCall({ name: tc.name, server: tc.server, elapsed: 0 });
          toolTimerRef.current = setInterval(() => {
            setActiveToolCall((prev) =>
              prev
                ? { ...prev, elapsed: Math.floor((Date.now() - toolStartRef.current) / 1000) }
                : null,
            );
          }, 1000);
          break;
        }

        case "tool_result": {
          clearToolCallState();
          const tr = event.params as { name: string; result: string };
          setMessages((msgs) => [
            ...msgs,
            {
              id: nextMsgId(),
              role: "tool",
              content: tr.result,
              toolName: tr.name,
              timestamp: Date.now(),
            },
          ]);
          break;
        }

        case "done": {
          if (cancelledRef.current) {
            cancelledRef.current = false;
            break;
          }
          const done = event.params as {
            prompt_tokens: number;
            completion_tokens: number;
          };
          setPromptTokens((prev) => prev + done.prompt_tokens);
          setCompletionTokens((prev) => prev + done.completion_tokens);
          setStreamingContent((prev) => {
            if (prev.trim()) {
              setMessages((msgs) => [
                ...msgs,
                {
                  id: nextMsgId(),
                  role: "assistant",
                  content: prev,
                  timestamp: Date.now(),
                },
              ]);
            }
            return "";
          });
          setStreamingThinking("");
          setIsStreaming(false);
          resolveActiveChat();
          break;
        }

        case "error":
          clearToolCallState();
          setStreamingThinking("");
          setError((event.params as { message: string }).message);
          setIsStreaming(false);
          rejectActiveChat((event.params as { message: string }).message);
          break;
      }
    });

    backend.on("exit", (code: number) => {
      if (code !== 0) {
        const message = `Backend exited with code ${code}`;
        setError(message);
        rejectActiveChat(message);
      }
    });

    backend.start();

    return () => {
      backend.stop();
      if (toolTimerRef.current) {
        clearInterval(toolTimerRef.current);
        toolTimerRef.current = null;
      }
      rejectActiveChat("Backend stopped");
    };
  }, [args, clearToolCallState, pythonPath, rejectActiveChat, resolveActiveChat]);

  const cancelStream = useCallback(() => {
    if (!backendRef.current?.running) return;
    cancelledRef.current = true;
    backendRef.current.cancel();
    // Commit partial content and reset streaming state
    setStreamingContent((prev) => {
      if (prev.trim()) {
        setMessages((msgs) => [
          ...msgs,
          {
            id: nextMsgId(),
            role: "assistant",
            content: prev,
            timestamp: Date.now(),
          },
        ]);
      }
      return "";
    });
    setIsStreaming(false);
    setStreamingThinking("");
    clearToolCallState();
  }, [clearToolCallState]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!backendRef.current?.running) return;
      if (chatCompletionRef.current) {
        throw new Error("Already streaming a chat response");
      }
      cancelledRef.current = false;
      setMessages((msgs) => [
        ...msgs,
        { id: nextMsgId(), role: "user", content: text, timestamp: Date.now() },
      ]);
      setStreamingContent("");
      setStreamingThinking("");
      setIsStreaming(true);
      setError(null);
      await new Promise<void>((resolve, reject) => {
        chatCompletionRef.current = { resolve, reject };
        backendRef.current?.chat(text).catch((e) => {
          clearToolCallState();
          const message = e instanceof Error ? e.message : String(e);
          setError(message);
          setStreamingThinking("");
          setIsStreaming(false);
          rejectActiveChat(message);
        });
      });
    },
    [clearToolCallState, rejectActiveChat],
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

  const updateConfig = useCallback((patch: Partial<AppConfig>) => {
    setConfig((prev) => (prev ? { ...prev, ...patch } : prev));
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
    error,
    sendMessage,
    sendCommand,
    addSystemMessage,
    updateConfig,
    cancelStream,
    backend: backendRef.current!,
  };
}
