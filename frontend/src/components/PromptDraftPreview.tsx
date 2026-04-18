import React from "react";
import { Box, Text } from "ink";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { symbols } from "../theme/index.js";
import { basename } from "../utils/path.js";
import type { DraftConstructPreview, DraftFilePreview } from "../utils/prompt.js";

interface PromptDraftPreviewProps {
  files: DraftFilePreview[];
  constructs: DraftConstructPreview[];
  showRemovalHint: boolean;
}

interface DraftPreviewPanelProps {
  title: string;
  count: number;
  color: string;
  marginTop?: number;
  overflowCount: number;
  overflowLabel: string;
  children: React.ReactNode;
}

function PreviewBadge({
  text,
  color,
}: {
  text: string;
  color: string;
}): React.ReactElement {
  return <Text color={color}>[{text}]</Text>;
}

function DraftPreviewPanel({
  title,
  count,
  color,
  marginTop = 0,
  overflowCount,
  overflowLabel,
  children,
}: DraftPreviewPanelProps): React.ReactElement {
  return (
    <Box
      marginTop={marginTop}
      borderStyle="round"
      borderColor={color}
      paddingX={1}
      flexDirection="column"
    >
      <Box gap={1}>
        <Text color={color}>{symbols.triforceSmall}</Text>
        <Text color={color} bold>{title}</Text>
        <Text dimColor>{count}</Text>
      </Box>
      {children}
      {overflowCount > 0 ? <Text dimColor>  {overflowCount} more {overflowLabel} attached</Text> : null}
    </Box>
  );
}

function FilePreviewCards({ files }: { files: DraftFilePreview[] }): React.ReactElement {
  const { colors } = useSettingsContext();

  return (
    <DraftPreviewPanel
      title="attached files"
      count={files.length}
      color={colors.nayru}
      overflowCount={Math.max(0, files.length - 4)}
      overflowLabel="files"
    >
      {files.slice(0, 4).map((file) => {
        const origin = file.origin === "picker" ? "picked from workspace" : "inline mention";
        return (
          <Box key={file.path} flexDirection="column" paddingLeft={1} marginTop={1}>
            <Box gap={1}>
              <Text color={colors.nayru}>@{file.path}</Text>
              <Text color={colors.text} bold>{basename(file.path)}</Text>
              <PreviewBadge text={file.typeLabel} color={colors.accent} />
            </Box>
            <Box gap={1} paddingLeft={2} flexWrap="wrap">
              <Text color={file.status === "resolved" ? colors.success : colors.warning}>
                {file.status === "resolved" ? "workspace file confirmed" : "loading file metadata"}
              </Text>
              <Text dimColor>{symbols.dot} {origin}</Text>
              {file.status === "resolved" ? <Text dimColor>{symbols.dot} {file.lines} lines</Text> : null}
              {file.status === "resolved" ? <Text dimColor>{symbols.dot} {file.chars} chars</Text> : null}
            </Box>
            {file.snippet ? (
              <Box paddingLeft={2} flexDirection="column">
                {file.snippet.split("\n").map((line, index) => (
                  <Text key={`${file.path}-snippet-${index}`} dimColor>
                    {index === 0 ? `${symbols.arrowRight} ${line}` : `  ${line}`}
                  </Text>
                ))}
              </Box>
            ) : null}
          </Box>
        );
      })}
    </DraftPreviewPanel>
  );
}

function ConstructPreviewCards({
  constructs,
  marginTop,
}: {
  constructs: DraftConstructPreview[];
  marginTop?: number;
}): React.ReactElement {
  const { colors } = useSettingsContext();

  return (
    <DraftPreviewPanel
      title="attached game refs"
      count={constructs.length}
      color={colors.accent}
      marginTop={marginTop}
      overflowCount={Math.max(0, constructs.length - 4)}
      overflowLabel="refs"
    >
      {constructs.slice(0, 4).map((preview) => {
        const meta = [preview.source, preview.detail].filter(Boolean).join(" · ");
        const statusColor = preview.status === "resolved"
          ? colors.success
          : preview.status === "suggested"
            ? colors.accent
            : colors.warning;
        const statusText = preview.status === "resolved"
          ? "project ref confirmed"
          : preview.status === "suggested"
            ? "best project match"
            : preview.status === "ambiguous"
              ? `${preview.matchCount} close matches`
              : "no project match in index";
        return (
          <Box key={preview.token} flexDirection="column" paddingLeft={1} marginTop={1}>
            <Box gap={1}>
              <Text color={preview.status === "resolved" ? colors.accent : colors.warning}>{preview.token}</Text>
              <Text color={colors.text} bold>{preview.label ?? preview.query}</Text>
            </Box>
            <Box gap={1} paddingLeft={2} flexWrap="wrap">
              <Text color={statusColor}>{statusText}</Text>
              {meta ? <Text dimColor>{symbols.dot} {meta}</Text> : null}
            </Box>
          </Box>
        );
      })}
    </DraftPreviewPanel>
  );
}

export function PromptDraftPreview({
  files,
  constructs,
  showRemovalHint,
}: PromptDraftPreviewProps): React.ReactElement | null {
  const { colors } = useSettingsContext();

  if (files.length === 0 && constructs.length === 0) {
    return null;
  }

  return (
    <Box paddingLeft={2} flexDirection="column">
      {files.length > 0 ? <FilePreviewCards files={files} /> : null}
      {constructs.length > 0 ? <ConstructPreviewCards constructs={constructs} marginTop={files.length > 0 ? 1 : 0} /> : null}
      {showRemovalHint ? (
        <Text dimColor>Backspace on an empty prompt removes the last @file or #ref</Text>
      ) : null}
    </Box>
  );
}
