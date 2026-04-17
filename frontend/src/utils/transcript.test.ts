import test from "node:test";
import assert from "node:assert/strict";

import type { Message } from "../ipc/protocol.js";
import { groupMessages, shouldShowContextPanel } from "./transcript.js";

test("groupMessages keeps tool activity inside the originating turn", () => {
  const messages: Message[] = [
    { id: "u1", role: "user", content: "inspect this", timestamp: 1, turnId: "turn-1" },
    { id: "a1", role: "assistant", content: "checking", timestamp: 2, turnId: "turn-1", model: "nayru" },
    { id: "t1", role: "tool", content: "", timestamp: 3, turnId: "turn-1", toolGroup: "call-1", toolName: "read_file" },
    { id: "t2", role: "tool", content: "ok", timestamp: 4, turnId: "turn-1", toolGroup: "call-1", toolName: "read_file" },
    { id: "u2", role: "user", content: "next", timestamp: 5, turnId: "turn-2" },
  ];

  const grouped = groupMessages(messages);
  assert.equal(grouped.length, 2);
  assert.equal(grouped[0]?.messages.length, 4);
  assert.equal(grouped[1]?.turnId, "turn-2");
});

test("shouldShowContextPanel requires enough width and a closed settings panel", () => {
  assert.equal(shouldShowContextPanel(160, false), true);
  assert.equal(shouldShowContextPanel(120, false), false);
  assert.equal(shouldShowContextPanel(160, true), false);
});
