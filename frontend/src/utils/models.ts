import type { ModelInfo } from "../ipc/protocol.js";

const CLOUD_NAME_HINTS = ["claude", "gpt", "gemini", "orchestrator"];
const FAST_LANE_HINTS = ["oracle-fast", "oracle-main-fast"];
const ORACLE_MAIN_HINT = "oracle";
const LEGACY_ORACLE_MODEL_HINTS = [
  "oracle-main",
  "oracle-main-plan",
  "oracle-main-act",
  "switchhook",
  "switchhook-plan",
  "switchhook-act",
  "oracle-tools",
];

export function normalizeModelName(name: string): string {
  return name.trim().toLowerCase();
}

export function isPlanLikeModel(name: string): boolean {
  const lowered = normalizeModelName(name);
  return /(^|[-_])(plan|planner)([-_]|$)/.test(lowered);
}

export function isActionLikeModel(name: string): boolean {
  const lowered = normalizeModelName(name);
  return /(^|[-_])(act|action|executor)([-_]|$)/.test(lowered);
}

export function isToolLikeModel(name: string): boolean {
  const lowered = normalizeModelName(name);
  return /(^|[-_])(tool|tools|fast)([-_]|$)/.test(lowered);
}

export function isCloudLikeModel(name: string): boolean {
  const lowered = normalizeModelName(name);
  return CLOUD_NAME_HINTS.some((hint) => lowered.includes(hint));
}

export function isFastLaneModel(model: Pick<ModelInfo, "name" | "modelId" | "role"> | string): boolean {
  const values = typeof model === "string"
    ? [model]
    : [model.name, model.modelId, model.role];
  return values.some((value) => {
    const lowered = normalizeModelName(value);
    return FAST_LANE_HINTS.some((hint) => lowered === hint);
  });
}

export function isHeavyOptInModel(model: Pick<ModelInfo, "name" | "modelId" | "role"> | string): boolean {
  return isFastLaneModel(model);
}

export function modelOptInLabel(model: Pick<ModelInfo, "name" | "modelId" | "role"> | string): string {
  return isFastLaneModel(model) ? "fast lane" : "";
}

export function modelPickerDescription(model: Pick<ModelInfo, "name" | "modelId" | "role">): string {
  const parts = [model.role.trim(), modelOptInLabel(model)].filter(Boolean);
  return parts.join(" · ");
}

export function estimateContextWindow(modelName: string, models: ModelInfo[] = []): number {
  const info = models.find((model) => model.name === modelName || model.modelId === modelName);
  if (typeof info?.contextBudget === "number" && info.contextBudget > 0) {
    return info.contextBudget;
  }
  if (info?.provider && info.provider !== "studio") {
    return 200000;
  }

  const lowered = normalizeModelName(modelName);
  if (lowered === ORACLE_MAIN_HINT) {
    return 32768;
  }
  if (FAST_LANE_HINTS.includes(lowered)) {
    return 16384;
  }
  if (isPlanLikeModel(lowered) || isActionLikeModel(lowered)) {
    return 32768;
  }
  if (LEGACY_ORACLE_MODEL_HINTS.includes(lowered)) {
    return 32768;
  }
  if (isCloudLikeModel(lowered)) {
    return 200000;
  }
  return 8192;
}
