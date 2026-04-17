/**
 * Fixed-height transcript region with ink-scroll-view: message groups, welcome,
 * streaming block, subagents, and errors. Tracks "follow tail" for auto-scroll.
 */

import React, { useCallback, useEffect, useRef } from "react";
import { Box, Text } from "ink";
import { ScrollView, type ScrollViewRef } from "ink-scroll-view";
import { MessageBubble } from "./MessageBubble.js";
import { StreamingMessage } from "./StreamingMessage.js";
import { WelcomeBanner } from "./WelcomeBanner.js";
import { SubagentPanel } from "./SubagentPanel.js";
import { symbols } from "../theme/index.js";
import type { AppConfig } from "../ipc/protocol.js";
import type { MessageGroup } from "../utils/transcript.js";
import type { SubagentEntry } from "../utils/subagentState.js";

export interface TranscriptScrollProps {
  scrollRef: React.RefObject<ScrollViewRef | null>;
  viewportHeight: number;
  groupedMessages: MessageGroup[];
  themeColors: Record<string, string>;
  config: AppConfig;
  messagesLength: number;
  isStreaming: boolean;
  streamingContent: string;
  streamingThinking: string;
  activeToolCall: { name: string; server: string; elapsed: number } | null;
  subagents: SubagentEntry[];
  error: string | null;
}

export function TranscriptScroll({
  scrollRef,
  viewportHeight,
  groupedMessages,
  themeColors,
  config,
  messagesLength,
  isStreaming,
  streamingContent,
  streamingThinking,
  activeToolCall,
  subagents,
  error,
}: TranscriptScrollProps): React.ReactElement {
  const atBottomRef = useRef(true);

  const onScroll = useCallback(
    (offset: number) => {
      const r = scrollRef.current;
      if (!r) return;
      const bottom = r.getBottomOffset();
      if (bottom <= 0) {
        atBottomRef.current = true;
        return;
      }
      atBottomRef.current = offset >= bottom - 1;
    },
    [scrollRef],
  );

  useEffect(() => {
    const r = scrollRef.current;
    if (!r) return;
    r.remeasure();
    if (atBottomRef.current) {
      const t = setTimeout(() => r.scrollToBottom(), 0);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [scrollRef, viewportHeight]);

  useEffect(() => {
    if (!atBottomRef.current) return;
    const r = scrollRef.current;
    if (!r) return;
    const t = setTimeout(() => r.scrollToBottom(), 0);
    return () => clearTimeout(t);
  }, [
    scrollRef,
    groupedMessages,
    messagesLength,
    streamingContent,
    streamingThinking,
    isStreaming,
    error,
    subagents,
  ]);

  const showWelcome = messagesLength === 0 && !isStreaming;

  return (
    <Box height={viewportHeight} width="100%" flexDirection="column">
      <ScrollView ref={scrollRef} width="100%" flexGrow={1} onScroll={onScroll}>
        {groupedMessages.map((group) => {
          const hasFrame = group.messages.length > 1
            || group.messages.some((message) => message.role === "tool");
          if (!hasFrame) {
            const message = group.messages[0]!;
            return (
              <Box key={group.id} flexDirection="column" width="100%">
                <MessageBubble message={message} />
              </Box>
            );
          }

          const modelsInTurn = Array.from(new Set(
            group.messages
              .map((message) => message.model)
              .filter((value): value is string => Boolean(value)),
          ));
          return (
            <Box
              key={group.id}
              marginTop={1}
              borderStyle="round"
              borderColor={themeColors.triforce}
              paddingX={1}
              flexDirection="column"
              width="100%"
            >
              <Box gap={1}>
                <Text dimColor>{group.turnId}</Text>
                {modelsInTurn.length > 0 ? (
                  <Text dimColor>{symbols.dot} {modelsInTurn.join(" + ")}</Text>
                ) : null}
              </Box>
              {group.messages.map((message, index) => (
                <MessageBubble key={`${message.id}-${index}`} message={message} />
              ))}
            </Box>
          );
        })}

        {showWelcome ? (
          <Box key="welcome" flexDirection="column" width="100%">
            <WelcomeBanner config={config} />
          </Box>
        ) : null}

        {subagents.length > 0 ? (
          <Box key="subagents" flexDirection="column" width="100%">
            <SubagentPanel entries={subagents} />
          </Box>
        ) : null}

        {isStreaming ? (
          <Box key="streaming" flexDirection="column" width="100%">
            <StreamingMessage
              content={streamingContent}
              thinkingContent={streamingThinking}
              activeToolCall={activeToolCall}
            />
          </Box>
        ) : null}

        {error ? (
          <Box
            key="error"
            borderStyle="double"
            borderColor={themeColors.error}
            paddingX={1}
            flexDirection="column"
            width="100%"
          >
            <Box alignItems="center" width="100%">
              <Text bold color={themeColors.error}>{"=== YOU'VE MET WITH A TERRIBLE FATE ==="}</Text>
            </Box>
            <Box gap={1}>
              <Text color={themeColors.error}>{symbols.heart}</Text>
              <Text color={themeColors.error}>{error}</Text>
            </Box>
            <Box alignItems="center" width="100%">
              <Text bold color={themeColors.error}>=== GAME OVER ===</Text>
            </Box>
          </Box>
        ) : null}
      </ScrollView>
    </Box>
  );
}
