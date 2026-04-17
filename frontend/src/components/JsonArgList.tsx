/**
 * Shared key/value display for JSON tool arguments (permission dialog + tool bubbles).
 */

import React from "react";
import { Box, Text } from "ink";
import { colors } from "../theme/index.js";

/** Default max characters per value; keep tool rows and permission dialog aligned. */
export const JSON_ARG_MAX_WIDTH = 60;

export function truncateArgValue(s: string, maxWidth: number): string {
  return s.length > maxWidth ? s.slice(0, maxWidth - 3) + "..." : s;
}

interface JsonArgListProps {
  jsonStr: string;
  /** When true, keys use `colors.dim` and values normal text; when false, entire row is dim. */
  colored?: boolean;
  maxValueWidth?: number;
  paddingLeft?: number;
}

export function JsonArgList({
  jsonStr,
  colored = false,
  maxValueWidth = JSON_ARG_MAX_WIDTH,
  paddingLeft = 0,
}: JsonArgListProps): React.ReactElement | null {
  if (!jsonStr) return null;
  try {
    const obj = JSON.parse(jsonStr) as Record<string, unknown>;
    if (typeof obj !== "object" || obj === null) {
      return (
        <Box paddingLeft={paddingLeft}>
          <Text dimColor>{truncateArgValue(jsonStr, maxValueWidth)}</Text>
        </Box>
      );
    }
    const entries = Object.entries(obj);
    if (entries.length === 0) return null;
    return (
      <Box flexDirection="column" paddingLeft={paddingLeft}>
        {entries.map(([k, v]) => {
          const val = typeof v === "string" ? v : JSON.stringify(v);
          const display = truncateArgValue(val, maxValueWidth);
          return colored ? (
            <Box key={k} gap={1}>
              <Text color={colors.dim}>{k}:</Text>
              <Text>{display}</Text>
            </Box>
          ) : (
            <Text key={k} dimColor>
              {k}: {display}
            </Text>
          );
        })}
      </Box>
    );
  } catch {
    return (
      <Box paddingLeft={paddingLeft}>
        <Text dimColor>{truncateArgValue(jsonStr, maxValueWidth)}</Text>
      </Box>
    );
  }
}
