import type { ModelInfo } from "../ipc/protocol.js";

const CLOUD_NAME_HINTS = ["claude", "gpt", "gemini", "orchestrator"];
const FAST_LANE_HINTS = ["oracle-fast", "oracle-main-fast"];
const HEAVY_LANE_HINTS = ["oracle-mythic", "oracle-main-27b-v1", "switchhook", "switchhook-plan", "switchhook-act"];
const ORACLE_MAIN_HINT = "oracle";
const ORACLE_PRO_HINT = "oracle-pro";
const ORACLE_MYTHIC_HINT = "oracle-mythic";
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
  const values = typeof model === "string"
    ? [model]
    : [model.name, model.modelId, model.role];
  return values.some((value) => {
    const lowered = normalizeModelName(value);
    return HEAVY_LANE_HINTS.some((hint) => lowered === hint || lowered.includes("switchhook-27b"));
  });
}

export function modelOptInLabel(model: Pick<ModelInfo, "name" | "modelId" | "role"> | string): string {
  if (isFastLaneModel(model)) return "fast";
  if (isHeavyOptInModel(model)) return "manual heavy";
  return "";
}

export function modelPickerDescription(
  model: Pick<ModelInfo, "name" | "modelId" | "role" | "description">,
): string {
  const summary = (model.description || model.role).trim();
  const parts = [summary, modelOptInLabel(model)].filter(Boolean);
  return parts.join(" · ");
}

export function formatModelMemory(sizeBytes?: number): string {
  if (!sizeBytes || sizeBytes <= 0) return "";
  const gib = sizeBytes / (1024 ** 3);
  if (gib >= 10) return `${gib.toFixed(1)} GiB`;
  return `${gib.toFixed(2)} GiB`;
}

export function formatContextLength(contextLength?: number): string {
  if (!contextLength || contextLength <= 0) return "";
  if (contextLength >= 1000) return `ctx ${Math.round(contextLength / 1000)}k`;
  return `ctx ${contextLength}`;
}

export function formatModelEstimate(
  estimatedGpuBytes?: number,
  estimatedTotalBytes?: number,
): string {
  const gpu = formatModelMemory(estimatedGpuBytes);
  const total = formatModelMemory(estimatedTotalBytes);
  if (gpu && total) {
    if (gpu === total) return `gpu/total ${gpu}`;
    return `gpu ${gpu} · total ${total}`;
  }
  if (gpu) return `gpu ${gpu}`;
  if (total) return `total ${total}`;
  return "";
}

export function describeLoadedModelRuntime(
  model: Pick<ModelInfo, "sizeBytes" | "status" | "parallel" | "queued" | "contextLength" | "quantization" | "estimatedGpuBytes" | "estimatedTotalBytes">,
): string {
  const parts = [
    formatModelMemory(model.sizeBytes),
    model.status?.trim() || "",
    model.parallel && model.parallel > 0 ? `p${model.parallel}` : "",
    model.queued && model.queued > 0 ? `q${model.queued}` : "",
    formatContextLength(model.contextLength),
    model.quantization?.trim() || "",
    formatModelEstimate(model.estimatedGpuBytes, model.estimatedTotalBytes),
  ].filter(Boolean);
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
  if (lowered === ORACLE_PRO_HINT) {
    return 16384;
  }
  if (lowered === ORACLE_MYTHIC_HINT) {
    return 8192;
  }
  if (HEAVY_LANE_HINTS.includes(lowered)) {
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
