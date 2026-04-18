/**
 * Persistent banner surfaced when the backend shows signs of failing requests.
 * Driven by `shouldShowBackendErrorBanner` in utils/backendHealth.ts.
 */

import React from "react";
import { Box, Text } from "ink";
import { symbols } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { backendErrorHint } from "../utils/backendHealth.js";
import type { AppConfig } from "../ipc/protocol.js";

export function BackendErrorBanner({ config }: { config: AppConfig }): React.ReactElement {
  const { colors } = useSettingsContext();
  const hint = backendErrorHint({
    requestErrorCount: config.requestErrorCount,
    requestSuccessCount: config.requestSuccessCount,
    lastRequestStatus: config.lastRequestStatus,
  });
  const errors = config.requestErrorCount ?? 0;
  const success = config.requestSuccessCount ?? 0;
  return (
    <Box
      width="100%"
      borderStyle="double"
      borderColor={colors.error}
      paddingX={1}
      marginBottom={1}
    >
      <Box flexGrow={1} gap={1}>
        <Text color={colors.error} bold>{symbols.heart} backend errors</Text>
        <Text dimColor>{symbols.dot}</Text>
        <Text color={colors.error}>{hint}</Text>
      </Box>
      <Box gap={1}>
        <Text dimColor>{errors} err {symbols.dot} {success} ok</Text>
        <Text dimColor>{symbols.dot}</Text>
        <Text dimColor>[Esc] dismiss</Text>
      </Box>
    </Box>
  );
}
