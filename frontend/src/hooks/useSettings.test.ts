import test from "node:test";
import assert from "node:assert/strict";

import { normalizeSettings } from "./useSettings.js";

test("normalizeSettings repairs invalid persisted enum and boolean values", () => {
  const settings = normalizeSettings({
    theme: false as any,
    uiMode: true as any,
    showThinking: "always" as any,
    thinkingDetail: "giant" as any,
    collapseReasoning: "nope" as any,
    showTimestamps: "yes" as any,
    toolsIndicator: false,
    transcriptShowMessages: false,
  } as any);

  assert.equal(settings.theme, "hyrule");
  assert.equal(settings.uiMode, "chat");
  assert.equal(settings.showThinking, "transcript");
  assert.equal(settings.thinkingDetail, "preview");
  assert.equal(settings.collapseReasoning, true);
  assert.equal(Object.prototype.hasOwnProperty.call(settings, "transcriptShowMessages"), false);
  assert.equal(settings.showTimestamps, true);
  assert.equal(settings.toolsIndicator, false);
});

test("normalizeSettings defaults showDiagnostics to false and preserves explicit values", () => {
  const defaulted = normalizeSettings({});
  assert.equal(defaulted.showDiagnostics, false);

  const enabled = normalizeSettings({ showDiagnostics: true });
  assert.equal(enabled.showDiagnostics, true);

  const repaired = normalizeSettings({ showDiagnostics: "on" as any });
  assert.equal(repaired.showDiagnostics, false);
});
